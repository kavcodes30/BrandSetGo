"""Review orchestration and persistence.

Flow (blueprint section 11):
content version -> privacy pass -> policy snapshot -> evidence retrieval ->
parallel checkers -> reconciliation -> patch generation -> drift preview ->
risk score -> routing decision -> disclosure + audit + coaching events.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AgentDisagreement,
    AgentFinding,
    AIDisclosure,
    AuditEvent,
    Brand,
    CoachingEvent,
    ContentVersion,
    DriftCheck,
    ReviewRun,
    RiskPolicy,
    RewritePatch,
    RoutingDecision,
    utcnow,
)
from app.orchestrator.graph import StateGraph, fan_out
from app.schemas import FindingDraft
from app.legal import ai as legal_ai
from app.legal import checker as legal_checker
from app.services import ai_review, classify, media
from app.services import drift as drift_svc
from app.services import genesis, passport, privacy, retrieval, rewrite, risk, routing, sarvam
from app.services.agents import accessibility, claims, facts, language, reconcile, tone, visual
from app.services.agents.base import AgentContext
from app.services.llm import mode

CHECKERS = {
    "tone": tone.run,
    "facts": facts.run,
    "claims": claims.run,
    "visual": visual.run,
    "accessibility": accessibility.run,
    "language": language.run,
}

LESSONS = {
    "R-01": "Substantiate before you promise: every duration, efficacy or clinical claim needs an approved source document.",
    "R-02": "Copy the product sheet, not your memory: sizes, quantities and prices are the most common fact drift.",
    "R-03": "Restricted words are brand damage: keep to the approved vocabulary list.",
    "R-04": "Approved assets only: off-palette or logo-less visuals read as a different brand.",
    "R-05": "Accessibility is measurable: 4.5:1 contrast and alt text on every image.",
    "R-06": "Translations are brand surfaces too: use glossary terms and keep disclaimers intact.",
    "R-07": "Cosmetics cannot claim to cure or treat. Describe the benefit instead.",
}


def _timeout_state(brand: Brand, content: ContentVersion) -> dict:
    """A review that ran out of time is a partial review, never a silent pass."""
    return {
        "findings": [],
        "errors": {"graph": f"review exceeded {settings.review_timeout_seconds:.0f}s"},
        "disagreements": [],
        "patches": [],
        "rules": [],
        "claims": [],
        "products": [],
        "assets": [],
        "glossary": [],
        "agents_expected": ["tone", "facts", "claims", "visual", "accessibility", "legal"],
        "agents_returned": [],
        "ai_classification": None,
        "ai_meta": {},
        "legal_meta": {"called": False, "error": "timeout"},
        "classification": {
            "declared": content.sensitivity,
            "effective": content.sensitivity,
            "detections": [],
            "policy": privacy.POLICY_BY_SENSITIVITY.get(content.sensitivity, privacy.POLICY_BY_SENSITIVITY["internal"]),
        },
        "policy_state": {},
        "redacted_text": content.body_text,
        "risk": {
            "score": 100,
            "band": "incomplete",
            "factors": [],
            "completeness": {
                "expected": ["tone", "facts", "claims", "visual", "accessibility", "legal"],
                "returned": [],
                "missing": ["tone", "facts", "claims", "visual", "accessibility", "legal"],
                "complete": False,
            },
            "hard_blocker": False,
            "raw_total": 100,
        },
        "routing": {
            "route": "specialist",
            "approver_role": "specialist",
            "reason": "The review did not finish in time, so it cannot be treated as safe. Retry or route to a specialist.",
            "auto_clear": False,
        },
    }


def content_hash(text: str, media_ref: str = "") -> str:
    return hashlib.sha256(f"{text}::{media_ref}".encode()).hexdigest()[:32]


def _audit(db: Session, run: ReviewRun, action: str, detail: dict | None = None, actor: str = "system") -> None:
    db.add(
        AuditEvent(
            org_id=run.org_id,
            brand_id=run.brand_id,
            actor=actor,
            action=action,
            object_type="review_run",
            object_ref=run.id,
            detail=detail or {},
        )
    )


def _uncovered_categories(brand_rules) -> list[str]:
    present = {r.category for r in brand_rules}
    return [c for c in ("tone", "facts", "claims", "visual", "accessibility") if c not in present]


def build_graph() -> StateGraph:
    graph = StateGraph("brand_review")

    async def preprocess(state: dict) -> dict:
        db: Session = state["db"]
        content: ContentVersion = state["content"]
        brand: Brand = state["brand"]
        products = retrieval.products_for(db, brand.id)
        classification = privacy.classify(
            content.body_text, content.sensitivity, [p for p in products if p.is_confidential]
        )
        content.sensitivity = classification["effective"]

        # Classification was produced at ingest; this reuses it (and only calls
        # the model if it is missing or the content changed).
        ai_class = await classify.classify_content_version(db, content, brand)
        # the label can only be raised by either layer
        content.sensitivity = classify.raise_label(content.sensitivity, ai_class.sensitivity)
        ai_class.sensitivity = content.sensitivity
        if content.item.language == "en" and ai_class.language in ("hi", "mr"):
            # trust the script detector over the declared language field
            content.item.language = ai_class.language

        redacted_text, redaction_map = privacy.redact(content.body_text, classification["detections"])
        content.redaction_map = redaction_map

        state["classification"] = classification
        state["ai_classification"] = ai_class
        state["redacted_text"] = redacted_text
        return state

    async def retrieve(state: dict) -> dict:
        db: Session = state["db"]
        brand: Brand = state["brand"]
        content: ContentVersion = state["content"]
        policy = retrieval.reviewable_policy(db, brand)
        state["policy"] = policy
        state["policy_state"] = {
            "id": policy.id if policy else None,
            "version": policy.version if policy else None,
            "status": policy.status if policy else "none",
            "enforced": bool(policy and policy.status == "published"),
            "rules": len(policy.rules) if policy else 0,
            "proposed_rules": len([r for r in policy.rules if not r.is_authoritative]) if policy else 0,
        }
        state["rules"] = retrieval.rules_for(db, policy, content.item.channel)
        state["claims"] = retrieval.claims_for(db, brand.id)
        state["products"] = retrieval.products_for(db, brand.id)
        state["assets"] = retrieval.assets_for(db, brand.id)
        state["glossary"] = retrieval.glossary_for(db, brand.id)
        return state

    async def check(state: dict) -> dict:
        content: ContentVersion = state["content"]
        brand: Brand = state["brand"]
        ctx = AgentContext(
            brand=brand,
            content=state["redacted_text"],
            channel=content.item.channel,
            language=content.item.language,
            sensitivity=content.sensitivity,
            meta={
                **(content.meta or {}),
                "media_ref": content.media_ref,
                "modality": content.item.modality,
            },
            rules=state["rules"],
            claims=state["claims"],
            products=state["products"],
            assets=state["assets"],
            glossary=state["glossary"],
            approved_examples=(brand.personality or {}).get("approved_examples", []),
        )
        selected = ["tone", "facts", "claims", "visual", "accessibility", "legal"]
        if content.item.language != "en" or content.meta.get("variant_of"):
            selected.append("language")

        results, errors = await fan_out(
            {name: (lambda n=name: CHECKERS[n](ctx)) for name in selected if name in CHECKERS}
        )
        drafts: list[FindingDraft] = []
        for name, raw in results.items():
            for item in raw:
                try:
                    drafts.append(FindingDraft(**item) if isinstance(item, dict) else item)
                except Exception:  # model output that fails the schema is dropped, not trusted
                    errors[name] = "schema validation failed"

        # legal scan against the guideline registry (deterministic)
        legal_drafts = legal_checker.scan(
            state["redacted_text"],
            sector=brand.sector,
            channel=content.item.channel,
            language=content.item.language,
        )
        drafts.extend(legal_drafts)

        # semantic pass: what pattern matching cannot see
        reported = [f.span_text for f in drafts if f.span_text and f.status != "pass"]
        ai_drafts, ai_meta = await ai_review.semantic_findings(
            content=state["redacted_text"],
            language=content.item.language,
            channel=content.item.channel,
            audience=content.item.audience or brand.audience,
            rules=state["rules"],
            claims=state["claims"],
            glossary=state["glossary"],
            already_reported=reported,
            classified_claims=[
                c.model_dump() for c in (state.get("ai_classification").claims if state.get("ai_classification") else [])
            ],
        )
        added = 0
        for f in ai_drafts:
            duplicate = any(
                d.agent == f.agent
                and d.span_text
                and f.span_text
                and (d.span_text.lower() == f.span_text.lower()
                     or f.span_text.lower() in d.span_text.lower()
                     or d.span_text.lower() in f.span_text.lower())
                for d in drafts
            )
            if duplicate:
                continue
            drafts.append(f)
            added += 1
        # legal pass: implied violations, mapped to the same registry
        legal_ai_drafts, legal_meta = await legal_ai.scan(
            state["redacted_text"],
            sector=brand.sector,
            channel=content.item.channel,
            language=content.item.language,
            already_reported=[f"{f.guideline_code}:{f.span_text}" for f in legal_drafts if f.span_text],
        )
        legal_added = 0
        for f in legal_ai_drafts:
            duplicate = any(
                d.guideline_code == f.guideline_code
                and d.span_text
                and f.span_text
                and (d.span_text.lower() in f.span_text.lower() or f.span_text.lower() in d.span_text.lower())
                for d in drafts
            )
            if duplicate:
                continue
            drafts.append(f)
            legal_added += 1
        legal_meta["added"] = legal_added
        state["legal_meta"] = legal_meta

        ai_meta["added"] = added
        ai_meta["legal"] = legal_meta
        state["ai_meta"] = ai_meta

        state["findings"] = drafts
        state["errors"] = errors
        state["agents_expected"] = selected
        state["agents_returned"] = sorted(set(results) | {"legal"})
        return state

    async def reconcile_node(state: dict) -> dict:
        drafts = reconcile.dedupe(state["findings"])
        state["findings"] = drafts
        state["disagreements"] = reconcile.find_disagreements(drafts)
        return state

    async def patches_node(state: dict) -> dict:
        content: ContentVersion = state["content"]
        state["patches"] = rewrite.build_patches(content.body_text, state["findings"])
        return state

    async def score_node(state: dict) -> dict:
        db: Session = state["db"]
        content: ContentVersion = state["content"]
        brand: Brand = state["brand"]
        finding_dicts = [
            {
                "agent": f.agent,
                "severity": f.severity,
                "status": f.status,
                "evidence_refs": f.evidence_refs,
            }
            for f in state["findings"]
        ]
        asset_novel = bool(content.media_ref) and not any(
            a.content_hash and a.content_hash == content.meta.get("asset_hash") for a in state["assets"]
        )
        result = risk.compute(
            finding_dicts,
            agents_expected=state["agents_expected"],
            agents_returned=state["agents_returned"],
            sensitivity=content.sensitivity,
            disagreement_count=len(state["disagreements"]),
            asset_novel=asset_novel,
            uncovered_categories=_uncovered_categories(state["rules"]),
        )
        state["risk"] = result

        policy_row = db.scalars(select(RiskPolicy).where(RiskPolicy.brand_id == brand.id)).first()
        state["routing"] = routing.decide(
            score=result["score"],
            band=result["band"],
            hard_blocker=result["hard_blocker"],
            completeness=result["completeness"],
            disagreement_count=len(state["disagreements"]),
            evidence_gaps=sum(1 for f in finding_dicts if any("none found" in e for e in f["evidence_refs"])),
            trust_score=brand.trust_score,
            sector=brand.sector,
            fast_track_max=policy_row.fast_track_max if policy_row else settings.fast_track_max,
            manager_max=policy_row.manager_max if policy_row else settings.manager_max,
            trust_floor=policy_row.trust_floor if policy_row else 0.55,
            auto_clear_enabled=policy_row.auto_clear_enabled if policy_row else False,
        )
        return state

    graph.add_node("preprocess", preprocess)
    graph.add_node("retrieve", retrieve)
    graph.add_node("check", check)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("patches", patches_node)
    graph.add_node("score", score_node)
    graph.set_entry_point("preprocess")
    graph.add_edge("preprocess", "retrieve")
    graph.add_edge("retrieve", "check")
    graph.add_edge("check", "reconcile")
    graph.add_edge("reconcile", "patches")
    graph.add_edge("patches", "score")
    graph.add_conditional_edges(
        "score",
        lambda s: "partial" if s["errors"] else "done",
        {"partial": "END", "done": "END"},
    )
    return graph


async def run_review(db: Session, content: ContentVersion, actor: str = "creator") -> ReviewRun:
    brand = db.get(Brand, content.brand_id)
    if brand is None:
        raise ValueError("brand not found")

    run = ReviewRun(
        org_id=brand.org_id,
        brand_id=brand.id,
        content_version_id=content.id,
        policy_version_id=(retrieval.reviewable_policy(db, brand).id if retrieval.reviewable_policy(db, brand) else None),
        status="reviewing",
        started_at=utcnow(),
        model=mode(),
        content_hash=content.content_hash or content_hash(content.body_text, content.media_ref),
    )
    db.add(run)
    db.flush()

    usage_before = sarvam.status()
    try:
        state = await asyncio.wait_for(
            build_graph().ainvoke({"db": db, "content": content, "brand": brand, "errors": {}}),
            timeout=settings.review_timeout_seconds,
        )
    except asyncio.TimeoutError:
        state = _timeout_state(brand, content)
    usage_after = sarvam.status()

    run.status = "partial" if state["errors"] else "completed"
    run.risk_score = state["risk"]["score"]
    run.risk_band = state["risk"]["band"]
    run.risk_factors = {
        "factors": state["risk"]["factors"],
        "raw_total": state["risk"]["raw_total"],
    }
    run.completeness = state["risk"]["completeness"]
    run.hard_blocker = state["risk"]["hard_blocker"]
    run.routing = state["routing"]
    run.finished_at = utcnow()

    ai_class = state.get("ai_classification")
    run.classification = ai_class.model_dump() if ai_class else {}
    semantic_meta = state.get("ai_meta", {}) or {}
    calls = (1 if ai_class and ai_class.source == "sarvam" else 0) + (1 if semantic_meta.get("called") else 0)
    run.modality = content.item.modality
    run.ai_meta = {
        "policy_state": state.get("policy_state", {}),
        "model": sarvam.model_name(),
        "semantic": semantic_meta,
        "legal": state.get("legal_meta", {}),
        "classification_source": ai_class.source if ai_class else "deterministic",
        "classification_latency_ms": ai_class.latency_ms if ai_class else 0,
        "calls": max(calls, usage_after["calls"] - usage_before["calls"]),
        "tokens_in": max(
            usage_after["tokens_in"] - usage_before["tokens_in"],
            (ai_class.tokens_in if ai_class else 0) + int(semantic_meta.get("tokens_in") or 0),
        ),
        "tokens_out": max(
            usage_after["tokens_out"] - usage_before["tokens_out"],
            (ai_class.tokens_out if ai_class else 0) + int(semantic_meta.get("tokens_out") or 0),
        ),
    }

    # findings
    finding_rows: dict[str, AgentFinding] = {}
    for idx, f in enumerate(state["findings"], start=1):
        start = content.body_text.find(f.span_text) if f.span_text else -1
        row = AgentFinding(
            review_run_id=run.id,
            finding_ref=f"F-{idx:02d}",
            agent=f.agent,
            rule_id=(next((r.id for r in state["rules"] if r.code == f.rule_code), None)),
            rule_code=f.rule_code,
            severity=f.severity,
            confidence=f.confidence,
            status=f.status,
            span_start=max(start, 0),
            span_end=max(start, 0) + len(f.span_text) if start >= 0 else 0,
            span_text=f.span_text,
            title=f.title,
            explanation=f.explanation,
            evidence_refs=f.evidence_refs,
            suggested_patch=(f.suggested_patch.model_dump() if f.suggested_patch else {}),
            source=f.source,
            guideline_code=f.guideline_code,
            guideline_title=f.guideline_title,
            guideline_authority=f.guideline_authority,
            guideline_citation=f.guideline_citation,
            legal_basis=f.legal_basis,
            remediation=f.remediation,
        )
        db.add(row)
        db.flush()
        finding_rows[row.finding_ref] = row

    for d in state["disagreements"]:
        db.add(
            AgentDisagreement(
                review_run_id=run.id,
                topic=d.topic,
                span_text=d.span_text,
                agent_a=d.agent_a,
                agent_a_status=d.agent_a_status,
                agent_b=d.agent_b,
                agent_b_status=d.agent_b_status,
                summary=d.summary,
            )
        )

    if content.transcript:
        media.attach_timecodes(list(finding_rows.values()), content.transcript)
        db.flush()

    # patches, linked back to the finding that justified them
    for p in state["patches"]:
        match = next((r for r in finding_rows.values() if r.span_text == p["original"]), None)
        db.add(
            RewritePatch(
                review_run_id=run.id,
                finding_id=match.id if match else None,
                start=p["start"],
                end=p["end"],
                original=p["original"],
                replacement=p["replacement"],
                reason=p["reason"],
                rule_code=p["rule_code"],
                evidence_refs=p["evidence_refs"],
            )
        )
    db.flush()

    # drift preview: what happens if every suggestion is accepted
    preview = rewrite.apply_patches(
        content.body_text,
        [
            {"start": p.start, "end": p.end, "replacement": p.replacement, "decision": "accepted"}
            for p in run.patches
        ],
    )
    drift_result = drift_svc.evaluate(
        content.body_text,
        preview,
        desired_cta=content.item.desired_cta,
        audience=content.item.audience or brand.audience,
        edited_spans=[(p.start, p.end) for p in run.patches],
    )
    db.add(
        DriftCheck(
            review_run_id=run.id,
            patch_id=None,
            similarity=drift_result["similarity"],
            invariants=drift_result["invariants"],
            passed=drift_result["passed"],
            blocking_reason=drift_result["blocking_reason"],
        )
    )

    db.add(
        RoutingDecision(
            review_run_id=run.id,
            route=state["routing"]["route"],
            approver_role=state["routing"]["approver_role"],
            reason=state["routing"]["reason"],
        )
    )

    # privacy disclosure record
    categories = [d["category"] for d in state["classification"]["detections"]]
    if ai_class and ai_class.claims:
        categories.append("extracted_claims")
    payload = privacy.disclosure_payload(
        run.id,
        brand.org_id,
        state["classification"],
        categories or ["brand copy"],
        tokens_in=run.ai_meta["tokens_in"],
        tokens_out=run.ai_meta["tokens_out"],
    )
    payload["calls"] = run.ai_meta["calls"]
    payload["latency_ms"] = run.ai_meta["classification_latency_ms"] + int(
        (run.ai_meta["semantic"] or {}).get("latency_ms") or 0
    )
    db.add(AIDisclosure(**payload))

    # coaching signals
    for f in state["findings"]:
        if f.status in ("confirmed", "needs_human_review") and f.rule_code:
            db.add(
                CoachingEvent(
                    brand_id=brand.id,
                    rule_code=f.rule_code,
                    category=f.agent,
                    lesson_key=LESSONS.get(f.rule_code, ""),
                )
            )

    blocking = [f for f in state["findings"] if f.status in ("confirmed", "needs_human_review")]
    if run.status == "partial":
        run.status = "needs_human"
    elif state["risk"]["hard_blocker"] or state["risk"]["band"] == "critical":
        run.status = "needs_human"
    elif blocking:
        run.status = "needs_changes"
    else:
        run.status = "ready_for_approval"

    _audit(db, run, "review.completed", {"risk": run.risk_score, "band": run.risk_band, "status": run.status}, actor)
    db.commit()
    db.refresh(run)
    return run


def decide_patch(db: Session, patch: RewritePatch, decision: str, edited_text: str | None, actor: str) -> dict:
    run = db.get(ReviewRun, patch.review_run_id)
    if run is None:
        raise ValueError("review not found")
    content = db.get(ContentVersion, run.content_version_id)

    patch.decision = decision
    patch.edited_text = edited_text
    patch.decided_by = actor
    patch.decided_at = utcnow()

    decisions = [
        {
            "start": p.start,
            "end": p.end,
            "replacement": p.replacement,
            "decision": p.decision,
            "edited_text": p.edited_text,
        }
        for p in run.patches
    ]
    brand = db.get(Brand, content.brand_id)
    revised = rewrite.apply_patches(content.body_text, decisions)
    result = drift_svc.evaluate(
        content.body_text,
        revised,
        desired_cta=content.item.desired_cta,
        audience=content.item.audience or (brand.audience if brand else ""),
        edited_spans=[(p.start, p.end) for p in run.patches if p.decision in ("accepted", "edited")],
    )
    db.add(
        DriftCheck(
            review_run_id=run.id,
            patch_id=patch.id,
            similarity=result["similarity"],
            invariants=result["invariants"],
            passed=result["passed"],
            blocking_reason=result["blocking_reason"],
        )
    )
    _audit(db, run, f"patch.{decision}", {"patch": patch.id, "drift_passed": result["passed"]}, actor)
    db.commit()
    return {"patch_id": patch.id, "drift": result, "revised_preview": revised}


def revise_content(db: Session, run: ReviewRun, actor: str) -> ContentVersion:
    """Create an immutable new version from accepted patches and re-review it."""
    content = db.get(ContentVersion, run.content_version_id)
    decisions = [
        {
            "start": p.start,
            "end": p.end,
            "replacement": p.replacement,
            "decision": p.decision,
            "edited_text": p.edited_text,
        }
        for p in run.patches
    ]
    revised_text = rewrite.apply_patches(content.body_text, decisions)

    passport.invalidate_for_item(db, content.content_item_id, "Content edited after clearance")

    item = content.item
    new_version = ContentVersion(
        content_item_id=item.id,
        brand_id=item.brand_id,
        version=content.version + 1,
        body_text=revised_text,
        media_ref=content.media_ref,
        content_hash=content_hash(revised_text, content.media_ref),
        sensitivity=content.sensitivity,
        meta={**(content.meta or {}), "derived_from": content.id},
        author_id=content.author_id,
    )
    db.add(new_version)
    db.flush()
    _audit(db, run, "content.revised", {"new_version": new_version.version}, actor)
    db.commit()
    return new_version
