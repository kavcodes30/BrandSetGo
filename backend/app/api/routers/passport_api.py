from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, get_ctx
from app.core.db import get_db
from app.api.serialize import iso
from app.models import (
    Approval,
    AuditEvent,
    Brand,
    Clearance,
    ContentItem,
    ContentVersion,
    PolicyVersion,
    ReviewRun,
)

router = APIRouter(prefix="/passports", tags=["passport"])
verify_router = APIRouter(prefix="/verify", tags=["passport"])


def _record(db, clearance: Clearance) -> dict:
    content = db.get(ContentVersion, clearance.content_version_id)
    item = db.get(ContentItem, content.content_item_id) if content else None
    brand = db.get(Brand, item.brand_id) if item else None
    policy = db.get(PolicyVersion, clearance.policy_version_id) if clearance.policy_version_id else None
    run = db.get(ReviewRun, clearance.review_run_id)
    approval = db.scalars(
        select(Approval).where(Approval.review_run_id == clearance.review_run_id).order_by(Approval.created_at.desc())
    ).first()
    history = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.object_ref == clearance.review_run_id)
            .order_by(AuditEvent.created_at)
        )
    )
    return {
        "clearance_id": clearance.clearance_id,
        "issued_at": iso(clearance.issued_at),
        "approver": clearance.approver,
        "risk_score": clearance.risk_score,
        "content_hash": clearance.content_hash,
        "verification_token": clearance.verification_token,
        "invalidated": clearance.invalidated,
        "invalidated_reason": clearance.invalidated_reason,
        "content": {
            "title": item.title if item else "",
            "version": content.version if content else 0,
            "body_text": content.body_text if content else "",
            "channel": item.channel if item else "",
            "language": item.language if item else "en",
        },
        "brand": {"id": brand.id, "name": brand.name} if brand else None,
        "policy_version": policy.version if policy else None,
        "review_id": clearance.review_run_id,
        "review_status": run.status if run else None,
        "decision": {
            "status": approval.status if approval else None,
            "by": approval.decided_by if approval else None,
            "comment": approval.comment if approval else "",
        },
        "history": [{"action": h.action, "actor": h.actor, "at": iso(h.created_at)} for h in history],
    }


@router.get("")
def list_passports(ctx: Ctx = Depends(get_ctx)):
    out = []
    for c in ctx.db.scalars(select(Clearance).order_by(Clearance.issued_at.desc())):
        run = ctx.db.get(ReviewRun, c.review_run_id)
        if run is None or run.org_id != ctx.org.id:
            continue
        out.append(_record(ctx.db, c))
    return out


@router.get("/{clearance_id}")
def get_passport(clearance_id: str, ctx: Ctx = Depends(get_ctx)):
    c = ctx.db.scalars(select(Clearance).where(Clearance.clearance_id == clearance_id)).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Clearance not found.")
    run = ctx.db.get(ReviewRun, c.review_run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Clearance not found in this workspace.")
    return _record(ctx.db, c)


@verify_router.get("/{clearance_id}")
def verify(clearance_id: str, db: Session = Depends(get_db)):
    """Public verification: anyone holding the link can check validity.

    Returns only validity, approver, versions and timestamps — never the copy,
    so a clearance can be shown to a client or an auditor without an account.
    """
    c = db.scalars(select(Clearance).where(Clearance.clearance_id == clearance_id)).first()
    if c is None:
        raise HTTPException(status_code=404, detail="No clearance with that ID.")
    content = db.get(ContentVersion, c.content_version_id)
    changed = bool(content and content.content_hash != c.content_hash)
    return {
        "clearance_id": c.clearance_id,
        "valid": (not c.invalidated) and (not changed),
        "issued_at": iso(c.issued_at),
        "approver": c.approver,
        "risk_score": c.risk_score,
        "content_hash_matches": not changed,
        "reason": c.invalidated_reason if c.invalidated else ("Content changed after clearance" if changed else ""),
    }
