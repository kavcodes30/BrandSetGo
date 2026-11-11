"""Brand Passport: version-locked clearance records.

A clearance is bound to the content hash and the policy version. Editing the
content or publishing a new policy invalidates it and forces a fresh review.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Clearance, ContentVersion, PolicyVersion, ReviewRun


def _next_clearance_id(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = len(list(db.scalars(select(Clearance.id)))) + 1
    return f"BSP-{year}-{count:04d}"


def token_for(content_hash: str, policy_version_id: str, clearance_id: str) -> str:
    raw = f"{content_hash}:{policy_version_id}:{clearance_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def issue(db: Session, run: ReviewRun, content: ContentVersion, policy: PolicyVersion | None, approver: str) -> Clearance:
    cid = _next_clearance_id(db)
    clearance = Clearance(
        review_run_id=run.id,
        content_version_id=content.id,
        content_hash=content.content_hash,
        policy_version_id=policy.id if policy else "",
        risk_score=run.risk_score or 0,
        approver=approver,
        clearance_id=cid,
        verification_token=token_for(content.content_hash, policy.id if policy else "", cid),
    )
    db.add(clearance)
    run.status = "passport_issued"
    db.flush()
    return clearance


def invalidate_for_item(db: Session, content_item_id: str, reason: str) -> list[Clearance]:
    versions = list(db.scalars(select(ContentVersion).where(ContentVersion.content_item_id == content_item_id)))
    ids = [v.id for v in versions]
    if not ids:
        return []
    rows = list(db.scalars(select(Clearance).where(Clearance.content_version_id.in_(ids), Clearance.invalidated.is_(False))))
    for c in rows:
        c.invalidated = True
        c.invalidated_reason = reason
    db.flush()
    return rows


def invalidate_for_policy(db: Session, brand_id: str, new_policy_version: int, new_policy_id: str) -> list[Clearance]:
    """A clearance is only valid under the policy version it was judged against."""
    runs = list(db.scalars(select(ReviewRun).where(ReviewRun.brand_id == brand_id)))
    if not runs:
        return []
    stale = list(
        db.scalars(
            select(Clearance).where(
                Clearance.review_run_id.in_([r.id for r in runs]),
                Clearance.policy_version_id != new_policy_id,
                Clearance.invalidated.is_(False),
            )
        )
    )
    for clearance in stale:
        clearance.invalidated = True
        clearance.invalidated_reason = (
            f"Policy v{new_policy_version} was published after this clearance. Re-review is required."
        )
    db.flush()
    return stale


def find(db: Session, clearance_id: str) -> Clearance | None:
    return db.scalars(select(Clearance).where(Clearance.clearance_id == clearance_id)).first()


def verify(db: Session, clearance_id: str) -> dict:
    c = find(db, clearance_id)
    if not c:
        return {"valid": False, "reason": "Clearance not found"}
    content = db.get(ContentVersion, c.content_version_id)
    content_changed = bool(content and content.content_hash != c.content_hash)
    valid = not c.invalidated and not content_changed
    return {
        "valid": valid,
        "clearance_id": c.clearance_id,
        "issued_at": c.issued_at,
        "approver": c.approver,
        "risk_score": c.risk_score,
        "policy_version_id": c.policy_version_id,
        "content_hash_matches": not content_changed,
        "invalidated_reason": c.invalidated_reason if c.invalidated else ("Content changed after clearance" if content_changed else ""),
    }
