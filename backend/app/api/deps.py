"""Request identity and tenant context.

Session comes from an HttpOnly cookie (the browser) or an Authorization bearer
token (API clients). Every query downstream is scoped to `ctx.org.id`.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_token
from app.models import Membership, Organization, User

ROLE_RANK = {"viewer": 0, "creator": 1, "reviewer": 2, "manager": 3, "legal": 4, "admin": 5, "owner": 6}


@dataclass
class Ctx:
    db: Session
    user: User
    org: Organization
    membership: Membership
    role: str

    @property
    def platform_admin(self) -> bool:
        return self.user.platform_role in ("admin", "support")

    @property
    def account_type(self) -> str:
        return self.org.account_type

    def require(self, minimum: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK.get(minimum, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({self.role}) cannot do this. It needs '{minimum}'.",
            )

    def require_platform_admin(self) -> None:
        if not self.platform_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin only.")


def _token_from(request: Request) -> str | None:
    token = request.cookies.get(settings.cookie_name)
    if token:
        return token
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _resolve(request: Request, db: Session) -> Ctx | None:
    token = _token_from(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.get(User, payload.get("sub", ""))
    if user is None or user.status != "active":
        return None
    # a bumped token_version revokes every token issued before it
    if int(payload.get("v") or 1) != int(user.token_version or 1):
        return None
    from sqlalchemy import select

    org_id = payload.get("org")
    membership = (
        db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.org_id == org_id))
        if org_id
        else db.scalar(select(Membership).where(Membership.user_id == user.id))
    )
    if membership is None:
        return None
    org = db.get(Organization, membership.org_id)
    if org is None or org.status != "active":
        return None
    return Ctx(db=db, user=user, org=org, membership=membership, role=membership.role)


def get_ctx(request: Request, db: Session = Depends(get_db)) -> Ctx:
    ctx = _resolve(request, db)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ctx


def get_ctx_optional(request: Request, db: Session = Depends(get_db)) -> Ctx | None:
    return _resolve(request, db)
