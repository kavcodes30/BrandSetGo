"""Platform admin: every account, workspace, plan and usage figure.

This is the operator surface behind the pricing model: who is active, what they
pay, what they consume, and where the limits are being hit.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import iso
from app.models import AuditEvent, Brand, Invoice, MailMessage, Membership, Organization, ReviewRun, User
from app.schemas import PlanChange, StatusChange
from app.services import plans

router = APIRouter(prefix="/admin", tags=["admin"])


def _guard(ctx: Ctx) -> None:
    ctx.require_platform_admin()


@router.get("/overview")
def overview(ctx: Ctx = Depends(get_ctx)):
    _guard(ctx)
    db = ctx.db
    now = datetime.now(timezone.utc)
    since_30 = now - timedelta(days=30)

    users = list(db.scalars(select(User)))
    orgs = list(db.scalars(select(Organization)))
    active_users = [u for u in users if u.last_login_at and u.last_login_at.replace(tzinfo=timezone.utc) >= since_30]
    reviews_30 = list(db.scalars(select(ReviewRun).where(ReviewRun.created_at >= since_30)))
    all_reviews = list(db.scalars(select(ReviewRun)))

    ai_calls = sum(int((r.ai_meta or {}).get("calls") or 0) for r in reviews_30)
    tokens_in = sum(int((r.ai_meta or {}).get("tokens_in") or 0) for r in reviews_30)
    tokens_out = sum(int((r.ai_meta or {}).get("tokens_out") or 0) for r in reviews_30)

    revenue = plans.mrr_breakdown(orgs)
    plan_counts = Counter(o.plan for o in orgs)

    # sign-ups per week for the last 8 weeks
    weeks = []
    for i in range(7, -1, -1):
        start = (now - timedelta(days=7 * (i + 1))).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now if i == 0 else (now - timedelta(days=7 * i)).replace(hour=0, minute=0, second=0, microsecond=0)
        weeks.append(
            {
                "week_start": start.date().isoformat(),
                "signups": sum(
                    1
                    for u in users
                    if start <= (u.created_at if u.created_at.tzinfo else u.created_at.replace(tzinfo=timezone.utc)) < end
                ),
            }
        )

    reviews_by_org = Counter(r.org_id for r in all_reviews)
    top_orgs = sorted(orgs, key=lambda o: reviews_by_org.get(o.id, 0), reverse=True)[:6]

    recent = sorted(users, key=lambda u: u.created_at, reverse=True)[:8]
    memberships = {m.user_id: m for m in db.scalars(select(Membership))}

    return {
        "totals": {
            "users": len(users),
            "active_users_30d": len(active_users),
            "orgs": len(orgs),
            "creator_orgs": sum(1 for o in orgs if o.account_type == "creator"),
            "business_orgs": sum(1 for o in orgs if o.account_type == "business"),
            "reviews_30d": len(reviews_30),
            "reviews_total": len(all_reviews),
            "ai_calls_30d": ai_calls,
            "tokens_in_30d": tokens_in,
            "tokens_out_30d": tokens_out,
            "suspended_users": sum(1 for u in users if u.status != "active"),
        },
        "revenue": revenue,
        "plans": [
            {
                **{k: p[k] for k in ("code", "name", "account_type", "price_inr", "interval", "seats", "brands", "reviews_per_month")},
                "orgs": plan_counts.get(p["code"], 0),
            }
            for p in plans.PLANS.values()
        ],
        "signups_by_week": weeks,
        "top_orgs": [
            {
                "id": o.id,
                "name": o.name,
                "account_type": o.account_type,
                "plan": o.plan,
                "plan_name": (plans.get(o.plan) or {}).get("name", o.plan),
                "reviews": reviews_by_org.get(o.id, 0),
                "mrr_inr": plans.price_of(o.plan),
                "status": o.status,
            }
            for o in top_orgs
        ],
        "recent_users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "account_type": u.account_type,
                "platform_role": u.platform_role,
                "status": u.status,
                "created_at": iso(u.created_at),
                "org": (ctx.db.get(Organization, memberships[u.id].org_id).name if u.id in memberships else ""),
            }
            for u in recent
        ],
    }


@router.get("/users")
def users(
    query: str = "",
    plan: str = "",
    status: str = "",
    account_type: str = "",
    ctx: Ctx = Depends(get_ctx),
):
    _guard(ctx)
    db = ctx.db
    stmt = select(User).order_by(User.created_at.desc())
    if status:
        stmt = stmt.where(User.status == status)
    if account_type:
        stmt = stmt.where(User.account_type == account_type)
    rows = list(db.scalars(stmt))

    memberships = {m.user_id: m for m in db.scalars(select(Membership))}
    out = []
    for user in rows:
        membership = memberships.get(user.id)
        org = db.get(Organization, membership.org_id) if membership else None
        if plan and (org is None or org.plan != plan):
            continue
        if query and query.lower() not in f"{user.name} {user.email}".lower():
            continue
        reviews = db.scalar(select(func.count(ReviewRun.id)).where(ReviewRun.org_id == (org.id if org else ""))) or 0
        out.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "account_type": user.account_type,
                "platform_role": user.platform_role,
                "status": user.status,
                "role": membership.role if membership else "",
                "org_id": org.id if org else "",
                "org_name": org.name if org else "",
                "plan": org.plan if org else "",
                "plan_name": (plans.get(org.plan) or {}).get("name", org.plan) if org else "",
                "mrr_inr": plans.price_of(org.plan) if org else 0,
                "reviews": reviews,
                "created_at": iso(user.created_at),
                "last_login_at": iso(user.last_login_at),
            }
        )
    return out


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    status: StatusChange | None = None,
    ctx: Ctx = Depends(get_ctx),
):
    _guard(ctx)
    user = ctx.db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == ctx.user.id and status and status.status != "active":
        raise HTTPException(status_code=400, detail="You cannot suspend your own account.")
    if status:
        user.status = status.status
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            actor=ctx.user.name,
            action="admin.user_updated",
            object_type="user",
            object_ref=user.id,
            detail={"status": user.status, "by_platform_admin": True},
        )
    )
    ctx.db.commit()
    return {"id": user.id, "status": user.status}


@router.get("/orgs")
def orgs(ctx: Ctx = Depends(get_ctx)):
    _guard(ctx)
    db = ctx.db
    out = []
    for org in db.scalars(select(Organization).order_by(Organization.created_at.desc())):
        members = db.scalar(select(func.count(Membership.id)).where(Membership.org_id == org.id)) or 0
        brands = db.scalar(select(func.count(Brand.id)).where(Brand.org_id == org.id)) or 0
        usage = plans.usage(db, org)
        out.append(
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "account_type": org.account_type,
                "plan": org.plan,
                "plan_name": usage["plan_name"],
                "status": org.status,
                "seats_used": members,
                "seats_limit": usage["seats_limit"],
                "brands": brands,
                "reviews_this_month": usage["reviews_used"],
                "reviews_limit": usage["reviews_limit"],
                "mrr_inr": plans.price_of(org.plan),
                "created_at": iso(org.created_at),
            }
        )
    return out


@router.patch("/orgs/{org_id}/plan")
def change_plan(org_id: str, payload: PlanChange, ctx: Ctx = Depends(get_ctx)):
    _guard(ctx)
    org = ctx.db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    plan = plans.get(payload.plan)
    if plan is None:
        raise HTTPException(status_code=400, detail="Unknown plan.")
    if plan["account_type"] != org.account_type:
        raise HTTPException(
            status_code=400,
            detail=f"{plan['name']} is a {plan['account_type']} plan; this workspace is {org.account_type}.",
        )
    previous = org.plan
    org.plan = plan["code"]
    org.seats = plan["seats"]
    ctx.db.add(
        AuditEvent(
            org_id=org.id,
            actor=ctx.user.name,
            action="admin.plan_changed",
            object_type="organization",
            object_ref=org.id,
            detail={"from": previous, "to": org.plan},
        )
    )
    ctx.db.commit()
    return {"id": org.id, "plan": org.plan, "plan_name": plan["name"], "seats": org.seats}


@router.get("/invoices")
def invoices(ctx: Ctx = Depends(get_ctx)):
    _guard(ctx)
    rows = list(ctx.db.scalars(select(Invoice).order_by(Invoice.created_at.desc())))
    orgs = {o.id: o for o in ctx.db.scalars(select(Organization))}
    return [
        {
            "id": r.id,
            "number": r.number,
            "org": orgs[r.org_id].name if r.org_id in orgs else "",
            "org_id": r.org_id,
            "plan_from": r.plan_from,
            "plan_to": r.plan_to,
            "amount_inr": r.amount_inr,
            "status": r.status,
            "mode": r.mode,
            "note": r.note,
            "created_by": r.created_by,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


@router.get("/mail")
def mail_outbox(limit: int = 40, ctx: Ctx = Depends(get_ctx)):
    _guard(ctx)
    rows = list(ctx.db.scalars(select(MailMessage).order_by(MailMessage.created_at.desc()).limit(limit)))
    return [
        {
            "id": r.id,
            "to": r.to_email,
            "subject": r.subject,
            "body": r.body,
            "kind": r.kind,
            "status": r.status,
            "error": r.error,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]
