"""ORM -> JSON. Kept in one place so every screen reads the same shapes."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgentDisagreement,
    AgentFinding,
    AIDisclosure,
    Approval,
    ApprovedClaim,
    Asset,
    AuditEvent,
    Brand,
    BrandRule,
    Clearance,
    ContentItem,
    ContentVersion,
    DriftCheck,
    GlossaryTerm,
    Product,
    ReviewRun,
    RewritePatch,
    RoutingDecision,
)


def iso(dt):
    return dt.isoformat() if dt else None


def user_brief(user) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "initials": user.avatar_initials or user.name[:2].upper()}


def brand_brief(db: Session, brand: Brand) -> dict:
    # `current_policy` is the enforced (published) version; a draft is reported
    # separately so the UI can say "policy v2 drafted, not enforced yet".
    policy = brand.current_policy
    latest = max(brand.policy_versions, key=lambda p: p.version) if brand.policy_versions else None
    items = list(db.scalars(select(ContentItem).where(ContentItem.brand_id == brand.id)))
    runs = list(db.scalars(select(ReviewRun).where(ReviewRun.brand_id == brand.id)))
    open_runs = [r for r in runs if r.status in ("needs_changes", "needs_human", "ready_for_approval", "partial")]
    return {
        "id": brand.id,
        "name": brand.name,
        "kind": brand.kind,
        "kind_label": {"personal": "Creator", "business": "Business brand", "agency_client": "Client brand"}.get(brand.kind, brand.kind),
        "sector": brand.sector,
        "description": brand.description,
        "audience": brand.audience,
        "tone": brand.tone,
        "languages": brand.languages or [],
        "channels": brand.channels or [],
        "palette": brand.palette or {},
        "logo_url": brand.logo_url,
        "trust_score": brand.trust_score,
        "is_personal": brand.is_personal,
        "is_sample": brand.is_sample,
        "policy_version": policy.version if policy else (latest.version if latest else None),
        "policy_status": policy.status if policy else (latest.status if latest else "none"),
        "policy_approved_by": policy.approved_by if policy else None,
        "asset_count": len(list(db.scalars(select(Asset).where(Asset.brand_id == brand.id)))),
        "content_count": len(items),
        "open_reviews": len(open_runs),
        "created_at": iso(brand.created_at),
    }


def rule_row(rule: BrandRule) -> dict:
    return {
        "id": rule.id,
        "code": rule.code,
        "title": rule.title,
        "category": rule.category,
        "statement": rule.statement,
        "severity": rule.severity,
        "scope": rule.scope or [],
        "source_ref": rule.source_ref,
        "evidence_ref": rule.evidence_ref,
        "is_authoritative": rule.is_authoritative,
        "proposed_by_model": rule.proposed_by_model,
    }


def brand_detail(db: Session, brand: Brand) -> dict:
    policy = brand.current_policy
    data = brand_brief(db, brand)
    data.update(
        {
            "policy": {
                "id": policy.id,
                "version": policy.version,
                "status": policy.status,
                "approved_by": policy.approved_by,
                "approved_at": iso(policy.approved_at),
                "source_summary": policy.source_summary,
                "rules": [rule_row(r) for r in policy.rules],
            }
            if policy
            else None,
            "drafts": [
                {"version": p.version, "status": p.status, "rules": len(p.rules), "created_at": iso(p.created_at)}
                for p in brand.policy_versions
            ],
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "sku": p.sku,
                    "attributes": p.attributes or {},
                    "sheet_ref": p.sheet_ref,
                    "sheet_page": p.sheet_page,
                }
                for p in db.scalars(select(Product).where(Product.brand_id == brand.id))
            ],
            "claims": [
                {
                    "id": c.id,
                    "text": c.text,
                    "status": c.status,
                    "evidence_ref": c.evidence_ref,
                    "expires_at": iso(c.expires_at),
                }
                for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.brand_id == brand.id))
            ],
            "assets": [
                {
                    "id": a.id,
                    "name": a.name,
                    "kind": a.kind,
                    "content_hash": a.content_hash,
                    "palette": a.palette or [],
                    "has_logo": a.has_logo,
                    "alt_text": a.alt_text,
                }
                for a in db.scalars(select(Asset).where(Asset.brand_id == brand.id))
            ],
            "glossary": [glossary_row(g) for g in db.scalars(select(GlossaryTerm).where(GlossaryTerm.brand_id == brand.id))],
            "personality": brand.personality or {},
        }
    )
    return data


def glossary_row(g: GlossaryTerm) -> dict:
    return {
        "id": g.id,
        "term_en": g.term_en,
        "term_hi": g.term_hi,
        "term_mr": g.term_mr,
        "prohibited": g.prohibited or [],
        "notes": g.notes,
    }


def content_brief(db: Session, item: ContentItem) -> dict:
    latest = max(item.versions, key=lambda v: v.version) if item.versions else None
    brand = db.get(Brand, item.brand_id)
    latest_run = None
    if latest:
        latest_run = db.scalars(
            select(ReviewRun).where(ReviewRun.content_version_id == latest.id).order_by(ReviewRun.created_at.desc())
        ).first()
    return {
        "id": item.id,
        "title": item.title,
        "brand_id": item.brand_id,
        "brand_name": brand.name if brand else "",
        "channel": item.channel,
        "language": item.language,
        "campaign": item.campaign,
        "desired_cta": item.desired_cta,
        "audience": item.audience,
        "modality": item.modality,
        "created_at": iso(item.created_at),
        "version": latest.version if latest else 0,
        "version_id": latest.id if latest else None,
        "body_text": latest.body_text if latest else "",
        "sensitivity": latest.sensitivity if latest else "internal",
        "risk_score": latest_run.risk_score if latest_run else None,
        "risk_band": latest_run.risk_band if latest_run else None,
        "status": latest_run.status if latest_run else "draft",
        "review_id": latest_run.id if latest_run else None,
        "classification": {
            "language": (latest.meta or {}).get("classification", {}).get("language"),
            "content_type": (latest.meta or {}).get("classification", {}).get("content_type"),
            "category": (latest.meta or {}).get("classification", {}).get("category"),
            "sensitivity": (latest.meta or {}).get("classification", {}).get("sensitivity"),
            "source": (latest.meta or {}).get("classification", {}).get("source"),
            "claims": len((latest.meta or {}).get("classification", {}).get("claims") or []),
        }
        if latest
        else {},
    }


def finding_row(f: AgentFinding) -> dict:
    return {
        "id": f.id,
        "ref": f.finding_ref,
        "agent": f.agent,
        "rule_code": f.rule_code,
        "severity": f.severity,
        "confidence": f.confidence,
        "status": f.status,
        "span_start": f.span_start,
        "span_end": f.span_end,
        "span_text": f.span_text,
        "title": f.title,
        "explanation": f.explanation,
        "evidence_refs": f.evidence_refs or [],
        "suggested_patch": f.suggested_patch or {},
        "source": f.source or "deterministic",
        "guideline_code": f.guideline_code or "",
        "guideline_title": f.guideline_title or "",
        "guideline_authority": f.guideline_authority or "",
        "guideline_citation": f.guideline_citation or "",
        "legal_basis": f.legal_basis or "",
        "remediation": f.remediation or "",
        "timecode_start": f.timecode_start,
        "timecode_end": f.timecode_end,
    }


def disagreement_row(d: AgentDisagreement) -> dict:
    return {
        "id": d.id,
        "topic": d.topic,
        "span_text": d.span_text,
        "agent_a": d.agent_a,
        "agent_a_status": d.agent_a_status,
        "agent_b": d.agent_b,
        "agent_b_status": d.agent_b_status,
        "summary": d.summary,
        "resolution": d.resolution,
        "resolved_by": d.resolved_by,
        "resolved_at": iso(d.resolved_at),
    }


def patch_row(p: RewritePatch) -> dict:
    return {
        "id": p.id,
        "start": p.start,
        "end": p.end,
        "original": p.original,
        "replacement": p.replacement,
        "reason": p.reason,
        "rule_code": p.rule_code,
        "evidence_refs": p.evidence_refs or [],
        "decision": p.decision,
        "decided_by": p.decided_by,
        "edited_text": p.edited_text,
    }


def review_summary(db: Session, run: ReviewRun) -> dict:
    content = db.get(ContentVersion, run.content_version_id)
    item = db.get(ContentItem, content.content_item_id) if content else None
    brand = db.get(Brand, run.brand_id)
    approval = db.scalars(
        select(Approval).where(Approval.review_run_id == run.id).order_by(Approval.created_at.desc())
    ).first()
    return {
        "id": run.id,
        "status": run.status,
        "risk_score": run.risk_score,
        "risk_band": run.risk_band,
        "hard_blocker": run.hard_blocker,
        "brand_id": run.brand_id,
        "brand_name": brand.name if brand else "",
        "content_title": item.title if item else "",
        "content_id": item.id if item else "",
        "content_version": content.version if content else 0,
        "channel": item.channel if item else "",
        "language": item.language if item else "en",
        "created_at": iso(run.created_at),
        "finished_at": iso(run.finished_at),
        "route": (run.routing or {}).get("route"),
        "approver_role": (run.routing or {}).get("approver_role"),
        "approval_status": approval.status if approval else None,
        "approval_id": approval.id if approval else None,
        "blocking_findings": len(
            list(db.scalars(select(AgentFinding).where(AgentFinding.review_run_id == run.id, AgentFinding.status != "pass")))
        ),
    }


def review_full(db: Session, run: ReviewRun) -> dict:
    content = db.get(ContentVersion, run.content_version_id)
    item = db.get(ContentItem, content.content_item_id) if content else None
    brand = db.get(Brand, run.brand_id)
    policy = brand.current_policy if brand else None
    findings = list(db.scalars(select(AgentFinding).where(AgentFinding.review_run_id == run.id)))
    disagreements = list(db.scalars(select(AgentDisagreement).where(AgentDisagreement.review_run_id == run.id)))
    patches = list(db.scalars(select(RewritePatch).where(RewritePatch.review_run_id == run.id).order_by(RewritePatch.start)))
    drift = db.scalars(
        select(DriftCheck).where(DriftCheck.review_run_id == run.id).order_by(DriftCheck.created_at.desc())
    ).first()
    routing = db.scalars(select(RoutingDecision).where(RoutingDecision.review_run_id == run.id)).first()
    approval = db.scalars(
        select(Approval).where(Approval.review_run_id == run.id).order_by(Approval.created_at.desc())
    ).first()
    clearance = db.scalars(select(Clearance).where(Clearance.review_run_id == run.id)).first()
    disclosure = db.scalars(select(AIDisclosure).where(AIDisclosure.review_run_id == run.id)).first()

    data = review_summary(db, run)
    policy_state = (run.ai_meta or {}).get("policy_state") or {}
    data.update(
        {
            "model": run.model,
            "modality": run.modality or "text",
            # the version this review was judged against (draft or published)
            "policy_version": policy_state.get("version") or (policy.version if policy else None),
            "content": {
                "id": content.id if content else "",
                "version": content.version if content else 0,
                "body_text": content.body_text if content else "",
                "media_ref": content.media_ref if content else "",
                "sensitivity": content.sensitivity if content else "internal",
                "redaction_map": content.redaction_map if content else [],
                "hash": content.content_hash if content else "",
                "desired_cta": item.desired_cta if item else "",
                "audience": item.audience if item else "",
                "channel": item.channel if item else "",
                "language": item.language if item else "en",
                "modality": item.modality if item else "text",
                "title": item.title if item else "",
                "transcript": content.transcript if content else [],
                "duration_s": content.duration_s if content else 0.0,
            },
            "brand": brand_brief(db, brand) if brand else None,
            "findings": [finding_row(f) for f in findings],
            "disagreements": [disagreement_row(d) for d in disagreements],
            "patches": [patch_row(p) for p in patches],
            "drift": {
                "similarity": drift.similarity,
                "invariants": drift.invariants,
                "passed": drift.passed,
                "blocking_reason": drift.blocking_reason,
            }
            if drift
            else None,
            "classification": run.classification or {},
            "ai_meta": run.ai_meta or {},
            "policy_state": (run.ai_meta or {}).get("policy_state", {}),
            "risk_factors": run.risk_factors or {},
            "completeness": run.completeness or {},
            "routing": {
                "route": routing.route if routing else (run.routing or {}).get("route"),
                "approver_role": routing.approver_role if routing else (run.routing or {}).get("approver_role"),
                "reason": routing.reason if routing else (run.routing or {}).get("reason"),
                "auto_clear": (run.routing or {}).get("auto_clear", False),
            },
            "approval": {
                "id": approval.id,
                "status": approval.status,
                "approver_role": approval.approver_role,
                "requested_by": approval.requested_by,
                "decided_by": approval.decided_by,
                "comment": approval.comment,
            }
            if approval
            else None,
            "clearance": {
                "clearance_id": clearance.clearance_id,
                "issued_at": iso(clearance.issued_at),
                "approver": clearance.approver,
                "invalidated": clearance.invalidated,
                "verification_token": clearance.verification_token,
            }
            if clearance
            else None,
            "disclosure": {
                "processor": disclosure.processor,
                "model": disclosure.model,
                "region": disclosure.region,
                "sensitivity": disclosure.sensitivity,
                "data_categories": disclosure.data_categories,
                "retention": disclosure.retention,
                "redaction_version": disclosure.redaction_version,
            }
            if disclosure
            else None,
            "history": [
                {"action": e.action, "actor": e.actor, "at": iso(e.created_at), "detail": e.detail}
                for e in db.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.object_ref == run.id)
                    .order_by(AuditEvent.created_at.desc())
                )
            ],
        }
    )
    return data
