"""Sign-up, sign-in, session and profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import Ctx, get_ctx
from app.api.serialize import iso, user_brief
from app.core.config import settings
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import allow
from app.core.security import create_token
from app.models import Organization, User
from app.schemas import (
    LoginRequest,
    PasswordChange,
    ProfileUpdate,
    ResetPassword,
    ResetRequest,
    SignupRequest,
    SwitchWorkspace,
    WorkspaceCreate,
)
from app.services import auth as auth_svc
from app.services import mail, plans, sarvam

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=60 * 60 * 24 * settings.session_days,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _issue(db: Session, user: User, org: Organization, membership, response: Response) -> str:
    token = create_token(user.id, extra={"org": org.id, "v": int(user.token_version or 1)})
    _set_cookie(response, token)
    return token


def _session_payload(db: Session, user: User, org: Organization, membership) -> dict:
    return {
        "user": {**user_brief(user), "account_type": user.account_type, "platform_role": user.platform_role},
        "org": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "account_type": org.account_type,
            "plan": org.plan,
            "plan_name": (plans.get(org.plan) or {}).get("name", org.plan),
            "status": org.status,
        },
        "role": membership.role,
        "platform_admin": user.platform_role in ("admin", "support"),
        "usage": plans.usage(db, org),
        "workspaces": [
            {
                "id": m.org_id,
                "name": (db.get(Organization, m.org_id).name if db.get(Organization, m.org_id) else ""),
                "account_type": (db.get(Organization, m.org_id).account_type if db.get(Organization, m.org_id) else ""),
                "plan": (db.get(Organization, m.org_id).plan if db.get(Organization, m.org_id) else ""),
                "role": m.role,
            }
            for m in auth_svc.memberships_for(db, user)
        ],
        "model_mode": sarvam.model_name(),
        "live_models": sarvam.enabled(),
        "registry_version": __import__("app.legal.guidelines", fromlist=["REGISTRY_VERSION"]).REGISTRY_VERSION,
    }


@router.get("/plans")
def list_plans(account_type: str | None = None):
    """Public: the pricing table used by the sign-up page."""
    items = plans.for_account(account_type) if account_type else list(plans.PLANS.values())
    return [
        {
            "code": p["code"],
            "name": p["name"],
            "account_type": p["account_type"],
            "price_inr": p["price_inr"],
            "interval": p["interval"],
            "seats": p["seats"],
            "brands": p["brands"],
            "reviews_per_month": p["reviews_per_month"],
            "features": p["features"],
            "blurb": p["blurb"],
        }
        for p in items
    ]


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user, org, membership = auth_svc.signup(db, payload)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    _issue(db, user, org, membership, response)
    return _session_payload(db, user, org, membership)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if settings.rate_limit_enabled:
        key = f"login:{request.client.host if request.client else 'unknown'}"
        if not allow(key, settings.login_attempts_per_minute):
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait a minute and try again.")
    try:
        user, org, membership = auth_svc.login(db, payload.email, payload.password)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    _issue(db, user, org, membership, response)
    return _session_payload(db, user, org, membership)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    return _session_payload(ctx.db, ctx.user, ctx.org, ctx.membership)


@router.patch("/profile")
def update_profile(payload: ProfileUpdate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    if payload.name:
        ctx.user.name = payload.name.strip()[:120]
        ctx.user.avatar_initials = auth_svc.initials(ctx.user.name)
    if payload.company and ctx.account_type == "business":
        ctx.require("manager")
        ctx.org.name = payload.company.strip()[:160]
    if payload.billing_email is not None:
        ctx.require("owner")
        ctx.org.billing_email = payload.billing_email.strip()[:200]
    ctx.db.commit()
    return _session_payload(ctx.db, ctx.user, ctx.org, ctx.membership)


@router.post("/password")
def change_password(payload: PasswordChange, response: Response, ctx: Ctx = Depends(get_ctx)):
    try:
        auth_svc.change_password(ctx.db, ctx.user, payload.current_password, payload.new_password)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    # the change revoked every token, including this tab's: issue a fresh one
    _issue(ctx.db, ctx.user, ctx.org, ctx.membership, response)
    return {"ok": True, "sessions_revoked": True}


@router.post("/forgot-password")
def forgot_password(payload: ResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always answers the same way: never reveals whether an email has an account."""
    if settings.rate_limit_enabled:
        key = f"forgot:{request.client.host if request.client else 'unknown'}"
        if not allow(key, 5):
            raise HTTPException(status_code=429, detail="Too many reset requests. Wait a minute.")
    raw = auth_svc.request_password_reset(db, payload.email)
    if raw:
        user = db.scalar(__import__("sqlalchemy").select(User).where(User.email == payload.email.strip().lower()))
        link = f"{settings.public_base_url}/#/reset?token={raw}"
        mail.deliver(
            db,
            payload.email,
            "Reset your BrandSetGo password",
            mail.reset_body(user.name if user else "there", link),
            kind="password_reset",
        )
    return {"ok": True, "message": "If that email has an account, a reset link is on its way."}


@router.post("/reset-password")
def reset_password(payload: ResetPassword, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth_svc.reset_password(db, payload.token, payload.password)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    membership = auth_svc.membership_for(db, user)
    org = db.get(Organization, membership.org_id) if membership else None
    if org and membership:
        _issue(db, user, org, membership, response)
        return {"ok": True, "signed_in": True}
    return {"ok": True, "signed_in": False}


@router.post("/switch-workspace")
def switch_workspace(payload: SwitchWorkspace, response: Response, ctx: Ctx = Depends(get_ctx)):
    membership = next((m for m in auth_svc.memberships_for(ctx.db, ctx.user) if m.org_id == payload.org_id), None)
    if membership is None:
        raise HTTPException(status_code=404, detail="You are not a member of that workspace.")
    org = ctx.db.get(Organization, membership.org_id)
    if org is None or org.status != "active":
        raise HTTPException(status_code=403, detail="That workspace is suspended.")
    _issue(ctx.db, ctx.user, org, membership, response)
    return _session_payload(ctx.db, ctx.user, org, membership)


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, response: Response, ctx: Ctx = Depends(get_ctx)):
    try:
        org = auth_svc.create_workspace(ctx.db, ctx.user, payload.name, payload.account_type, payload.plan)
    except auth_svc.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    membership = next(m for m in auth_svc.memberships_for(ctx.db, ctx.user) if m.org_id == org.id)
    _issue(ctx.db, ctx.user, org, membership, response)
    return _session_payload(ctx.db, ctx.user, org, membership)
