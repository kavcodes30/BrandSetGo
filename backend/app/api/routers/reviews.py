from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.idempotency import cached, remember
from app.core.config import settings
from app.core.ratelimit import allow
from app.api.serialize import (
    disagreement_row,
    finding_row,
    iso,
    patch_row,
    review_full,
    review_summary,
)
from app.models import (
    AgentDisagreement,
    AgentFinding,
    AuditEvent,
    Brand,
    ContentVersion,
    ReviewRun,
    RewritePatch,
    utcnow,
)
from app.schemas import DisagreementResolution, PatchDecision, ReviewRequest
from app.services import plans, reviews as review_svc
from app.services import rewrite as rewrite_svc

router = APIRouter(prefix="/reviews", tags=["reviews"])
patches_router = APIRouter(prefix="/rewrite-patches", tags=["rewrite"])

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _run_or_404(ctx: Ctx, run_id: str) -> ReviewRun:
    run = ctx.db.get(ReviewRun, run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Review not found in this workspace.")
    return run


@router.get("")
def list_reviews(brand_id: str | None = None, limit: int = 50, ctx: Ctx = Depends(get_ctx)):
    stmt = select(ReviewRun).where(ReviewRun.org_id == ctx.org.id)
    if brand_id:
        stmt = stmt.where(ReviewRun.brand_id == brand_id)
    runs = list(ctx.db.scalars(stmt.order_by(ReviewRun.created_at.desc()).limit(limit)))
    return [review_summary(ctx.db, r) for r in runs]


@router.post("", status_code=201)
async def create_review(
    payload: ReviewRequest,
    request: Request,
    ctx: Ctx = Depends(get_ctx),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    ctx.require("creator")
    if settings.rate_limit_enabled and not allow(f"review:{ctx.org.id}", settings.reviews_per_minute):
        raise HTTPException(status_code=429, detail="Too many reviews in a minute. Give it a moment.")

    replay = cached(ctx.db, ctx.org.id, idempotency_key, "review.create")
    if replay is not None:
        return replay
    version = ctx.db.get(ContentVersion, payload.content_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Content version not found.")
    brand = ctx.db.get(Brand, version.brand_id)
    if brand is None or brand.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Content version not found in this workspace.")

    block = plans.quota_block_reason(ctx.db, ctx.org)
    if block:
        raise HTTPException(status_code=402, detail=block)

    run = await review_svc.run_review(ctx.db, version, ctx.user.name)
    result = review_full(ctx.db, run)
    remember(ctx.db, ctx.org.id, idempotency_key, "review.create", result)
    ctx.db.commit()
    return result


@router.get("/{run_id}")
def get_review(run_id: str, ctx: Ctx = Depends(get_ctx)):
    return review_full(ctx.db, _run_or_404(ctx, run_id))


@router.get("/{run_id}/panel")
def get_panel(run_id: str, ctx: Ctx = Depends(get_ctx)):
    run = _run_or_404(ctx, run_id)
    findings = list(ctx.db.scalars(select(AgentFinding).where(AgentFinding.review_run_id == run.id)))
    disagreements = list(
        ctx.db.scalars(select(AgentDisagreement).where(AgentDisagreement.review_run_id == run.id))
    )

    agents: dict[str, dict] = {}
    for agent in ("tone", "facts", "claims", "visual", "accessibility", "language"):
        rows = [f for f in findings if f.agent == agent]
        if not rows:
            continue
        blocking = [f for f in rows if f.status in ("confirmed", "needs_human_review")]
        worst = min(
            (f.severity for f in blocking), key=lambda s: SEVERITY_ORDER.get(s, 9), default="low"
        )
        agents[agent] = {
            "agent": agent,
            "verdict": "blocked" if blocking else ("uncertain" if any(f.status == "inconclusive" for f in rows) else "approved"),
            "worst_severity": worst if blocking else "none",
            "confidence": round(sum(f.confidence for f in rows) / len(rows), 2),
            "findings": [finding_row(f) for f in rows],
            "checked": True,
        }

    expected = (run.completeness or {}).get("expected", [])
    for agent in expected:
        agents.setdefault(
            agent,
            {
                "agent": agent,
                "verdict": "unavailable",
                "worst_severity": "unknown",
                "confidence": 0,
                "findings": [],
                "checked": False,
            },
        )

    return {
        "review_id": run.id,
        "status": run.status,
        "model": run.model,
        "agents": list(agents.values()),
        "disagreements": [disagreement_row(d) for d in disagreements],
        "completeness": run.completeness,
        "reconciliation_note": (
            "Findings are deduplicated; contradictions are kept and must be resolved by a human."
        ),
    }


@router.get("/{run_id}/risk")
def get_risk(run_id: str, ctx: Ctx = Depends(get_ctx)):
    run = _run_or_404(ctx, run_id)
    findings = list(ctx.db.scalars(select(AgentFinding).where(AgentFinding.review_run_id == run.id)))
    return {
        "review_id": run.id,
        "score": run.risk_score,
        "band": run.risk_band,
        "hard_blocker": run.hard_blocker,
        "factors": (run.risk_factors or {}).get("factors", []),
        "completeness": run.completeness,
        "routing": run.routing,
        "blocking_findings": [
            finding_row(f) for f in findings if f.status in ("confirmed", "needs_human_review")
        ],
        "disclaimer": "Risk is decision support, not a compliance guarantee.",
    }


@router.get("/{run_id}/drift")
def get_drift(run_id: str, ctx: Ctx = Depends(get_ctx)):
    run = _run_or_404(ctx, run_id)
    full = review_full(ctx.db, run)
    patches = [patch_row(p) for p in run.patches]
    decisions = [
        {
            "id": p["id"],
            "original": p["original"],
            "replacement": p["replacement"],
            "decision": p["decision"],
            "reason": p["reason"],
        }
        for p in patches
    ]
    revised = rewrite_svc.apply_patches(
        full["content"]["body_text"],
        [
            {
                "start": p.start,
                "end": p.end,
                "replacement": p.replacement,
                "decision": p.decision if p.decision != "pending" else "rejected",
                "edited_text": p.edited_text,
            }
            for p in run.patches
        ],
    )
    return {
        "review_id": run.id,
        "original": full["content"]["body_text"],
        "revised_preview": revised,
        "patches": decisions,
        "drift": full["drift"],
        "warning": "Semantic similarity is a warning signal, not proof of equal meaning.",
    }


@router.post("/{run_id}/revise")
async def revise(run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    run = _run_or_404(ctx, run_id)
    if not any(p.decision in ("accepted", "edited") for p in run.patches):
        raise HTTPException(status_code=400, detail="Accept at least one edit before creating a revised version.")
    new_version = review_svc.revise_content(ctx.db, run, ctx.user.name)
    new_run = await review_svc.run_review(ctx.db, new_version, ctx.user.name)
    return {"content_version": new_version.version, "review": review_full(ctx.db, new_run)}


@router.post("/{run_id}/disagreements/{disagreement_id}/resolve")
def resolve_disagreement(
    run_id: str, disagreement_id: str, payload: DisagreementResolution, ctx: Ctx = Depends(get_ctx)
):
    ctx.require("reviewer")
    run = _run_or_404(ctx, run_id)
    row = ctx.db.get(AgentDisagreement, disagreement_id)
    if row is None or row.review_run_id != run.id:
        raise HTTPException(status_code=404, detail="Disagreement not found on this review.")
    row.resolution = payload.resolution
    row.resolved_by = payload.resolved_by or ctx.user.name
    row.resolved_at = utcnow()
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=run.brand_id,
            actor=ctx.user.name,
            action="disagreement.resolved",
            object_type="review_run",
            object_ref=run.id,
            detail={"disagreement": row.id, "resolution": payload.resolution},
        )
    )
    ctx.db.commit()
    return disagreement_row(row)


@router.post("/{run_id}/override")
def override(run_id: str, justification: str, ctx: Ctx = Depends(get_ctx)):
    """A critical finding may only be bypassed by an authorised role, with a reason."""
    ctx.require("legal")
    run = _run_or_404(ctx, run_id)
    if not justification.strip():
        raise HTTPException(status_code=400, detail="An override requires a written justification.")
    run.hard_blocker = False
    run.status = "ready_for_approval"
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=run.brand_id,
            actor=ctx.user.name,
            action="review.overridden",
            object_type="review_run",
            object_ref=run.id,
            detail={"justification": justification, "role": ctx.role},
        )
    )
    ctx.db.commit()
    return {"review_id": run.id, "status": run.status, "justification": justification}


@patches_router.post("/{patch_id}/decision")
def decide_patch(patch_id: str, payload: PatchDecision, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    patch = ctx.db.get(RewritePatch, patch_id)
    if patch is None:
        raise HTTPException(status_code=404, detail="Patch not found.")
    run = ctx.db.get(ReviewRun, patch.review_run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Patch not found in this workspace.")

    result = review_svc.decide_patch(
        ctx.db, patch, payload.decision, payload.edited_text, payload.decided_by or ctx.user.name
    )
    if payload.decision in ("accepted", "edited") and not result["drift"]["passed"]:
        # the decision is stored, but automatic acceptance is blocked
        return {
            **result,
            "blocked": True,
            "message": "Meaning drift detected: revise this edit before the content can be re-reviewed.",
        }
    return {**result, "blocked": False}
