from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import brand_brief, iso, review_summary, user_brief
from app.core.config import settings
from app.core.timeutils import as_utc
from app.models import (
    AgentFinding,
    Approval,
    Brand,
    BrandRule,
    Clearance,
    ContentVersion,
    Membership,
    ReviewRun,
    User,
)
from app.schemas import FindingDraft, QuickCheckRequest
from app.services import coaching as coaching_svc
from app.services import sarvam
from app.services import insights as insights_svc
from app.services import risk as risk_svc
from app.services import routing as routing_svc
from app.services.agents import accessibility, claims, facts, reconcile, tone, visual
from app.services.agents.base import AgentContext
from app.services.genesis import STARTER_RULES
from app.services.llm import mode
from app.services.seed import seed_demo

router = APIRouter(tags=["workspace"])

STATES = [
    ("DRAFT", "Created but not submitted"),
    ("SUBMITTED", "Content version frozen and queued"),
    ("PREPROCESSING", "Sensitivity label, redaction, parsing"),
    ("REVIEWING", "Independent checkers running"),
    ("NEEDS_CHANGES", "Blocking findings returned to the creator"),
    ("NEEDS_HUMAN", "Disagreement, missing evidence or critical claim"),
    ("READY_FOR_APPROVAL", "Checks complete, routed to an approver"),
    ("APPROVED", "Human decision recorded"),
    ("PASSPORT_ISSUED", "Clearance locked to content and policy version"),
    ("PUBLISHED", "Released outside the workspace"),
]

STATE_MAP = {
    "queued": "SUBMITTED",
    "reviewing": "REVIEWING",
    "needs_changes": "NEEDS_CHANGES",
    "needs_human": "NEEDS_HUMAN",
    "ready_for_approval": "READY_FOR_APPROVAL",
    "approved": "APPROVED",
    "passport_issued": "PASSPORT_ISSUED",
    "completed": "REVIEWING",
    "partial": "NEEDS_HUMAN",
}


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    """Session summary (kept for the app shell; /auth/me carries the same shape)."""
    members = list(ctx.db.scalars(select(Membership).where(Membership.org_id == ctx.org.id)))
    users = []
    for m in members:
        u = ctx.db.get(User, m.user_id)
        if u:
            users.append({**user_brief(u), "role": m.role})
    return {
        "user": {**user_brief(ctx.user), "account_type": ctx.user.account_type},
        "role": ctx.role,
        "org": {"id": ctx.org.id, "name": ctx.org.name, "account_type": ctx.org.account_type, "plan": ctx.org.plan},
        "members": users,
        "platform_admin": ctx.platform_admin,
        "model_mode": mode(),
        "live_models": settings.live_models,
    }


@router.get("/ai/status")
async def ai_status(probe: bool = False, ctx: Ctx = Depends(get_ctx)):
    """Provider status for the Privacy Center: what is on, what it has cost."""
    data = sarvam.status()
    if probe and data["enabled"]:
        data["probe"] = await sarvam.health()
    return data


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(get_ctx)):
    brands = list(ctx.db.scalars(select(Brand).where(Brand.org_id == ctx.org.id).order_by(Brand.created_at)))
    runs = list(
        ctx.db.scalars(
            select(ReviewRun).where(ReviewRun.org_id == ctx.org.id).order_by(ReviewRun.created_at.desc())
        )
    )
    approvals = list(ctx.db.scalars(select(Approval).where(Approval.status == "pending")))
    org_runs = {r.id for r in runs}
    pending = [
        a
        for a in approvals
        if a.review_run_id in org_runs
    ]
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # one row per content item, using its newest review, so counts read like a worklist
    latest_by_item: dict[str, ReviewRun] = {}
    for run in runs:
        version = ctx.db.get(ContentVersion, run.content_version_id)
        if version is None:
            continue
        current = latest_by_item.get(version.content_item_id)
        if current is None or run.created_at > current.created_at:
            latest_by_item[version.content_item_id] = run
    latest_runs = list(latest_by_item.values())
    clearances = [
        c
        for c in ctx.db.scalars(select(Clearance))
        if any(r.id == c.review_run_id for r in runs) and not c.invalidated
    ]
    return {
        "counts": {
            "waiting": len(pending),
            "cleared_this_month": len([c for c in clearances if as_utc(c.issued_at) and as_utc(c.issued_at) >= month_start]),
            "need_changes": len([r for r in latest_runs if r.status == "needs_changes"]),
            "needs_human": len([r for r in latest_runs if r.status in ("needs_human", "partial")]),
            "total_reviews": len(runs),
        },
        "brands": [brand_brief(ctx.db, b) for b in brands],
        "recent_reviews": [review_summary(ctx.db, r) for r in runs[:6]],
        "pending_approvals": [
            {
                "id": a.id,
                "approver_role": a.approver_role,
                "requested_by": a.requested_by,
                "created_at": iso(a.created_at),
                "review": next((review_summary(ctx.db, r) for r in runs if r.id == a.review_run_id), None),
            }
            for a in pending[:5]
        ],
        "model_mode": mode(),
    }


@router.get("/coaching")
def coaching(brand_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    if brand_id:
        return coaching_svc.summary(ctx.db, brand_id)
    brands = list(ctx.db.scalars(select(Brand).where(Brand.org_id == ctx.org.id)))
    return {
        "brands": [
            {"brand": brand_brief(ctx.db, b), "coaching": coaching_svc.summary(ctx.db, b.id)} for b in brands
        ]
    }


@router.get("/insights")
def insights(brand_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    if brand_id:
        return insights_svc.brand_insights(ctx.db, brand_id)
    brands = list(ctx.db.scalars(select(Brand).where(Brand.org_id == ctx.org.id)))
    combined = {
        "brands": [
            {"brand": brand_brief(ctx.db, b), "insights": insights_svc.brand_insights(ctx.db, b.id)}
            for b in brands
        ]
    }
    return combined


@router.get("/workflow")
def workflow(ctx: Ctx = Depends(get_ctx)):
    runs = list(ctx.db.scalars(select(ReviewRun).where(ReviewRun.org_id == ctx.org.id)))
    counts = Counter(STATE_MAP.get(r.status, "REVIEWING") for r in runs)
    return {
        "states": [{"key": k, "label": k.replace("_", " ").title(), "description": d, "count": counts.get(k, 0)} for k, d in STATES],
        "flow": [
            "Select mode: Quick Check, Personal, Business or Agency",
            "Brand page: identity, audience, products, languages, assets",
            "Brand Genesis proposes rules; an owner approves a policy version",
            "Creator submits content with channel, audience, language, sensitivity",
            "Preprocess, redact, retrieve applicable rules and verified claims",
            "Independent Tone / Facts / Claims / Visual / Accessibility checkers",
            "Reconcile findings without hiding disagreements",
            "Anchored findings, evidence and Brand Risk Score",
            "Intent-preserving patches, per-change accept, drift check",
            "Re-review, route by risk and trust, human decision",
            "Version-locked Brand Passport; edits invalidate it",
        ],
        "failure_paths": [
            "Agent timeout → partial review, missing checks named, retry offered",
            "Missing claim evidence → marked unverified, source requested",
            "Low OCR or language confidence → human confirmation before enforcement",
            "Conflicting reviewers → both findings kept, routed for a human decision",
            "Sensitive content → external scope shown, redacted or denied per policy",
            "Version drift → content edits and policy changes force re-review",
            "Authorization → workspace-scoped roles, server-side checks",
        ],
    }


@router.post("/quick-check")
def quick_check(payload: QuickCheckRequest, ctx: Ctx = Depends(get_ctx)):
    """Review one item with default rules, no brand required."""
    virtual_brand = Brand(
        id="quick-check",
        org_id=ctx.org.id,
        name="Quick Check",
        kind="personal",
        sector="",
        audience="",
        tone="",
        languages=[payload.language],
        channels=[payload.channel],
        personality={"banned_terms": []},
        palette={},
    )
    rules = [
        BrandRule(
            id=f"qc-{i}",
            policy_version_id="quick-check",
            code=r["code"],
            title=r["title"],
            category=r["category"],
            statement=r["statement"],
            severity=r["severity"],
            scope=[],
            source_ref="Quick Check defaults",
            evidence_ref=r["evidence_ref"],
            is_authoritative=True,
        )
        for i, r in enumerate(STARTER_RULES)
    ]
    agent_ctx = AgentContext(
        brand=virtual_brand,
        content=payload.body_text,
        channel=payload.channel,
        language=payload.language,
        sensitivity="internal",
        meta={"modality": "text"},
        rules=rules,
    )
    raw = []
    for fn in (tone.run, facts.run, claims.run, visual.run, accessibility.run):
        raw.extend(fn(agent_ctx))
    findings = reconcile.dedupe(raw)
    disagreements = reconcile.find_disagreements(findings)
    scoring = risk_svc.compute(
        [{"agent": f.agent, "severity": f.severity, "status": f.status, "evidence_refs": f.evidence_refs} for f in findings],
        agents_expected=["tone", "facts", "claims", "visual", "accessibility"],
        agents_returned=["tone", "facts", "claims", "visual", "accessibility"],
        sensitivity="internal",
        disagreement_count=len(disagreements),
        asset_novel=False,
        uncovered_categories=[],
    )
    route = routing_svc.decide(
        score=scoring["score"],
        band=scoring["band"],
        hard_blocker=scoring["hard_blocker"],
        completeness=scoring["completeness"],
        disagreement_count=len(disagreements),
        evidence_gaps=0,
        trust_score=0.5,
        sector="",
        fast_track_max=settings.fast_track_max,
        manager_max=settings.manager_max,
        trust_floor=0.55,
        auto_clear_enabled=False,
    )
    return {
        "mode": "quick_check",
        "findings": [FindingDraft(**f.model_dump()).model_dump() for f in findings],
        "disagreements": [d.__dict__ for d in disagreements],
        "risk": scoring,
        "routing": route,
        "note": "Quick Check applies default rules only. Create a brand page to enforce your own policy.",
    }


@router.post("/admin/reseed")
async def reseed(ctx: Ctx = Depends(get_ctx)):
    ctx.require("owner")
    result = await seed_demo(ctx.db)
    if not result.get("seeded"):
        raise HTTPException(status_code=409, detail="Workspace already contains data.")
    return result
