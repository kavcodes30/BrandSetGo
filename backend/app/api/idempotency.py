"""Idempotency keys: a retried POST returns the first result, never a duplicate."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


def cached(db: Session, org_id: str, key: str | None, scope: str) -> dict | None:
    if not key:
        return None
    row = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.org_id == org_id, IdempotencyKey.key == key[:120], IdempotencyKey.scope == scope
        )
    )
    return row.response if row else None


def remember(db: Session, org_id: str, key: str | None, scope: str, response: dict) -> None:
    if not key:
        return
    db.add(
        IdempotencyKey(org_id=org_id, key=key[:120], scope=scope, response=response)
    )
