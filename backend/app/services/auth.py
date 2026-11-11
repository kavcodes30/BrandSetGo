"""Sign-up, sign-in and workspace bootstrap.

One workspace per account: a creator gets a personal workspace with a single
personal brand; a business gets a team workspace that starts empty and invites
members. The first account created on a fresh install becomes the platform admin
(switchable with FIRST_USER_IS_ADMIN).
"""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import hash_password, password_problems, verify_password
from app.models import (
    ActionToken,
    AuditEvent,
    Brand,
    Membership,
    Organization,
    PolicyVersion,
    User,
    utcnow,
)
from app.schemas import SignupRequest
from app.services import genesis, plans

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "auth_error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _slug(base: str, db: Session) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "workspace"
    candidate, n = slug, 1
    while db.scalar(select(Organization).where(Organization.slug == candidate)):
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "BS"


def _first_user_is_admin(db: Session) -> bool:
    admins = db.scalar(select(func.count(User.id)).where(User.platform_role == "admin")) or 0
    total = db.scalar(select(func.count(User.id))) or 0
    return settings.first_user_is_admin and admins == 0 and total == 0


def signup(db: Session, payload: SignupRequest) -> tuple[User, Organization, Membership]:
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("That email address does not look right.")
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("An account with that email already exists. Sign in instead.", status=409)

    problems = password_problems(payload.password)
    if problems:
        raise AuthError(" ".join(problems))

    account_type = payload.account_type
    if account_type == "business" and len(payload.company.strip()) < 2:
        raise AuthError("A business account needs a company name.")

    plan_code = payload.plan or plans.DEFAULT_PLAN[account_type]
    plan = plans.get(plan_code)
    if plan is None or plan["account_type"] != account_type:
        plan_code = plans.DEFAULT_PLAN[account_type]

    is_admin = _first_user_is_admin(db)

    org = Organization(
        name=(payload.company.strip() if account_type == "business" else f"{payload.name.strip()}'s workspace"),
        slug=_slug(payload.company or payload.name, db),
        account_type=account_type,
        plan=plan_code,
        seats=plans.get(plan_code)["seats"],
        billing_email=email,
    )
    db.add(org)
    db.flush()

    user = User(
        email=email,
        name=payload.name.strip(),
        avatar_initials=initials(payload.name),
        password_hash=hash_password(payload.password),
        account_type=account_type,
        platform_role="admin" if is_admin else None,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.flush()

    org.created_by = user.id
    membership = Membership(org_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    db.flush()

    if account_type == "creator":
        brand = Brand(
            org_id=org.id,
            name=f"{payload.name.strip()}'s Brand",
            kind="personal",
            sector="creator",
            description="Personal brand created at sign-up.",
            audience="",
            tone="",
            languages=["en"],
            channels=["instagram_caption"],
            personality={"banned_terms": [], "approved_examples": []},
            palette={"colors": ["#1B2A21", "#FFFDF7"], "text": "#1B2A21", "background": "#FFFDF7"},
            owner_id=user.id,
            owner_user_id=user.id,
            is_personal=True,
        )
        db.add(brand)
        db.flush()
        genesis.create_policy(db, brand, genesis.starter_rules(brand), "Creator starter set")

    db.add(
        AuditEvent(
            org_id=org.id,
            brand_id=None,
            actor=user.name,
            action="account.created",
            object_type="organization",
            object_ref=org.id,
            detail={"account_type": account_type, "plan": plan_code, "platform_admin": is_admin},
        )
    )
    db.commit()
    db.refresh(user)
    db.refresh(org)
    return user, org, membership


def login(db: Session, email: str, password: str) -> tuple[User, Organization, Membership]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise AuthError("Email or password is incorrect.", status=401)
    if user.status != "active":
        raise AuthError("This account is suspended. Contact support.", status=403)

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    if membership is None:
        raise AuthError("This account has no workspace.", status=403)
    org = db.get(Organization, membership.org_id)
    if org is None:
        raise AuthError("Workspace not found.", status=403)
    if org.status != "active":
        raise AuthError("This workspace is suspended. Contact support.", status=403)

    user.last_login_at = utcnow()
    db.commit()
    return user, org, membership


def membership_for(db: Session, user: User) -> Membership | None:
    return db.scalar(select(Membership).where(Membership.user_id == user.id))


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthError("Current password is incorrect.", status=401)
    problems = password_problems(new)
    if problems:
        raise AuthError(" ".join(problems))
    user.password_hash = hash_password(new)
    user.token_version = (user.token_version or 1) + 1  # kill sessions issued before the change
    db.commit()


def memberships_for(db: Session, user: User) -> list[Membership]:
    return list(db.scalars(select(Membership).where(Membership.user_id == user.id)))


def create_workspace(db: Session, user: User, name: str, account_type: str, plan_code: str) -> Organization:
    """A second workspace for the same person: an agency, a side brand, a client."""
    plan = plans.get(plan_code) or plans.get(plans.DEFAULT_PLAN.get(account_type, "business_starter"))
    if plan is None:
        raise AuthError("Unknown plan.")
    if plan["account_type"] != account_type:
        raise AuthError("That plan does not match the workspace type.")

    org = Organization(
        name=name.strip()[:160] or f"{user.name}'s workspace",
        slug=_slug(name or user.name, db),
        account_type=account_type,
        plan=plan["code"],
        seats=plan["seats"],
        billing_email=user.email,
        created_by=user.id,
    )
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    db.flush()

    if account_type == "creator":
        brand = Brand(
            org_id=org.id,
            name=f"{name.strip() or user.name}'s Brand",
            kind="personal",
            sector="creator",
            description="Personal brand created with the workspace.",
            languages=["en"],
            channels=["instagram_caption"],
            personality={"banned_terms": [], "approved_examples": []},
            palette={"colors": ["#1B2A21", "#FFFDF7"], "text": "#1B2A21", "background": "#FFFDF7"},
            owner_id=user.id,
            owner_user_id=user.id,
            is_personal=True,
        )
        db.add(brand)
        db.flush()
        genesis.create_policy(db, brand, genesis.starter_rules(brand), "Creator starter set")

    db.add(
        AuditEvent(
            org_id=org.id,
            actor=user.name,
            action="workspace.created",
            object_type="organization",
            object_ref=org.id,
            detail={"account_type": account_type, "plan": plan["code"]},
        )
    )
    db.commit()
    db.refresh(org)
    return org


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def request_password_reset(db: Session, email: str) -> str | None:
    """Create a single-use reset token. Returns the raw token (None if no such user).

    The caller must always answer the same way, so this cannot be used to probe
    which emails have accounts.
    """
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.status != "active":
        return None
    raw = secrets.token_urlsafe(32)
    db.add(
        ActionToken(
            user_id=user.id,
            purpose="password_reset",
            token_hash=_token_hash(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    db.commit()
    return raw


def reset_password(db: Session, raw_token: str, new_password: str) -> User:
    token = db.scalar(select(ActionToken).where(ActionToken.token_hash == _token_hash(raw_token)))
    if token is None or token.used_at is not None:
        raise AuthError("That reset link is not valid any more. Request a new one.", status=400)
    expires = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise AuthError("That reset link has expired. Request a new one.", status=400)

    problems = password_problems(new_password)
    if problems:
        raise AuthError(" ".join(problems))

    user = db.get(User, token.user_id)
    if user is None:
        raise AuthError("Account not found.", status=400)
    user.password_hash = hash_password(new_password)
    user.token_version = (user.token_version or 1) + 1  # revoke existing sessions
    token.used_at = utcnow()
    db.commit()
    return user
