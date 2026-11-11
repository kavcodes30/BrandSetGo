"""Creator dashboard, business dashboard and team management."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import brand_brief, iso, review_summary, user_brief
from app.core.security import hash_password, password_problems
from app.models import (
    AgentFinding,
    Approval,
    AuditEvent,
    Brand,
    Clearance,
    ContentItem,
    ContentVersion,
    Membership,
    ReviewRun,
    User,
    utcnow,
)
from app.schemas import MemberInvite, MemberRoleUpdate
from app.services import coaching as coaching_svc, mail
from app.services import plans
from app.services.auth import initials

router = APIRouter(prefix="/workspace", tags=["workspace"])

MANAGER_ROLES = {"owner", "admin"}


def _runs(db, org_id: str, since: datetime | None = None):
    stmt = select(ReviewRun).where(ReviewRun.org_id == org_id).order_by(ReviewRun.created_at.desc())
    if since:
        stmt = stmt.where(ReviewRun.created_at >= since)
    return list(db.scalars(stmt))


@router.get("/creator")
def creator_overview(ctx: Ctx = Depends(get_ctx)):
    """Everything one creator needs: their brand, policy, reviews, coaching, quota."""
    if ctx.account_type != "creator" and not ctx.platform_admin:
        raise HTTPException(status_code=403, detail="This is the creator dashboard. Your account is a business workspace.")

    db = ctx.db
    brand = db.scalar(
        select(Brand).where(Brand.org_id == ctx.org.id).order_by(Brand.created_at)
    )
    usage = plans.usage(db, ctx.org)
    runs = _runs(db, ctx.org.id)
    content = list(db.scalars(select(ContentItem).where(ContentItem.org_id == ctx.org.id).order_by(ContentItem.created_at.desc())))
    findings = (
        list(db.scalars(select(AgentFinding).where(AgentFinding.review_run_id.in_([r.id for r in runs]))))
        if runs
        else []
    )
    clearances = list(db.scalars(select(Clearance).where(Clearance.review_run_id.in_([r.id for r in runs])))) if runs else []
    legal = [f for f in findings if f.agent == "legal" and f.status in ("confirmed", "needs_human_review")]

    # published policy is what is enforced; a draft still has to be reported so
    # the creator sees "approve your policy" rather than "no policy"
    policy = brand.current_policy if brand else None
    latest = max(brand.policy_versions, key=lambda p: p.version) if brand and brand.policy_versions else None
    next_actions = []
    if brand and policy and policy.status != "published":
        next_actions.append(
            {"label": "Approve your brand policy", "detail": "Nothing is enforced until you approve the rules.", "href": f"#/brands/{brand.id}/dna"}
        )
    if not brand or brand.audience == "":
        next_actions.append({"label": "Finish your brand profile", "detail": "Audience and voice make every check sharper.", "href": f"#/brands/{brand.id}/dna" if brand else "#/genesis"})
    if usage["reviews_used"] == 0:
        next_actions.append({"label": "Run your first check", "detail": "Paste a caption, script or transcript.", "href": "#/studio"})
    if legal:
        next_actions.append({
            "label": f"{len(legal)} legal {'flag needs' if len(legal) == 1 else 'flags need'} attention",
            "detail": "Open the review to see the exact guideline and what to change.",
            "href": f"#/reviews/{legal[0].review_run_id}",
        })

    return {
        "account": {
            "name": ctx.user.name,
            "email": ctx.user.email,
            "initials": ctx.user.avatar_initials or initials(ctx.user.name),
            "plan": usage["plan_name"],
            "member_since": iso(ctx.user.created_at),
        },
        "usage": usage,
        "brand": brand_brief(db, brand) if brand else None,
        "policy": {
            "version": policy.version if policy else (latest.version if latest else None),
            "status": policy.status if policy else (latest.status if latest else "none"),
            "approved_by": policy.approved_by if policy else None,
            "rules": len(policy.rules) if policy else (len(latest.rules) if latest else 0),
            "enforced": policy is not None,
        },
        "next_actions": next_actions,
        "counts": {
            "reviews": len(runs),
            "content_items": len(content),
            "open_flags": len([f for f in findings if f.status in ("confirmed", "needs_human_review")]),
            "legal_flags": len(legal),
            "cleared": len([c for c in clearances if not c.invalidated]),
            "needs_changes": len([r for r in runs if r.status == "needs_changes"]),
        },
        "recent_reviews": [review_summary(db, r) for r in runs[:6]],
        "recent_content": [
            {
                "id": item.id,
                "title": item.title,
                "channel": item.channel,
                "language": item.language,
                "modality": item.modality,
                "created_at": iso(item.created_at),
            }
            for item in content[:6]
        ],
        "coaching": coaching_svc.summary(db, brand.id) if brand else None,
    }


@router.get("/business")
def business_overview(ctx: Ctx = Depends(get_ctx)):
    """Team view: every brand, its health, the approval queue and the team."""
    if ctx.account_type != "business" and not ctx.platform_admin:
        raise HTTPException(status_code=403, detail="This is the business dashboard. Your account is a creator workspace.")

    db = ctx.db
    brands = list(db.scalars(select(Brand).where(Brand.org_id == ctx.org.id).order_by(Brand.created_at)))
    runs = _runs(db, ctx.org.id)
    usage = plans.usage(db, ctx.org)
    now = datetime.now(timezone.utc)
    since_30 = now - timedelta(days=30)

    brand_rows = []
    for brand in brands:
        brand_runs = [r for r in runs if r.brand_id == brand.id]
        open_runs = [r for r in brand_runs if r.status in ("needs_changes", "needs_human", "partial")]
        scores = [r.risk_score for r in brand_runs if r.risk_score is not None]
        policy = brand.current_policy
        brand_rows.append(
            {
                **brand_brief(db, brand),
                "avg_risk": round(sum(scores) / len(scores), 1) if scores else None,
                "reviews": len(brand_runs),
                "open": len(open_runs),
                "last_review": iso(brand_runs[0].created_at) if brand_runs else None,
                "policy_published": bool(policy and policy.status == "published"),
            }
        )

    members = []
    for membership in db.scalars(select(Membership).where(Membership.org_id == ctx.org.id)):
        user = db.get(User, membership.user_id)
        if user:
            members.append({**user_brief(user), "role": membership.role, "last_login_at": iso(user.last_login_at), "status": user.status})

    pending = list(
        db.scalars(
            select(Approval).where(
                Approval.status == "pending",
                Approval.review_run_id.in_([r.id for r in runs] or [""]),
            )
        )
    )

    weeks = []
    for i in range(7, -1, -1):
        start = now - timedelta(days=7 * (i + 1))
        end = now - timedelta(days=7 * i)
        weeks.append({"week_start": start.date().isoformat(), "reviews": sum(1 for r in runs if start <= r.created_at.replace(tzinfo=timezone.utc) < end)})

    findings = list(db.scalars(select(AgentFinding).where(AgentFinding.review_run_id.in_([r.id for r in runs] or [""]))))
    blocking = [f for f in findings if f.status in ("confirmed", "needs_human_review")]

    return {
        "org": {
            "id": ctx.org.id,
            "name": ctx.org.name,
            "account_type": ctx.org.account_type,
            "plan": usage["plan_name"],
            "plan_code": usage["plan"],
            "billing_email": ctx.org.billing_email,
            "created_at": iso(ctx.org.created_at),
        },
        "usage": usage,
        "counts": {
            "brands": len(brands),
            "members": len(members),
            "reviews": len(runs),
            "reviews_30d": len([r for r in runs if r.created_at.replace(tzinfo=timezone.utc) >= since_30]),
            "pending_approvals": len(pending),
            "open_findings": len(blocking),
            "legal_flags": len([f for f in blocking if f.agent == "legal"]),
            "cleared": db.scalar(select(func.count(Clearance.id))) or 0,
        },
        "brands": brand_rows,
        "members": members,
        "pending_approvals": [
            {
                "id": a.id,
                "approver_role": a.approver_role,
                "requested_by": a.requested_by,
                "created_at": iso(a.created_at),
                "review": next((review_summary(db, r) for r in runs if r.id == a.review_run_id), None),
            }
            for a in pending[:6]
        ],
        "recent_reviews": [review_summary(db, r) for r in runs[:8]],
        "reviews_by_week": weeks,
        "issue_mix": [
            {"agent": agent, "count": count}
            for agent, count in Counter(f.agent for f in blocking).most_common()
        ],
    }


@router.get("/members")
def members(ctx: Ctx = Depends(get_ctx)):
    out = []
    for membership in ctx.db.scalars(select(Membership).where(Membership.org_id == ctx.org.id)):
        user = ctx.db.get(User, membership.user_id)
        if user:
            out.append({**user_brief(user), "role": membership.role, "status": user.status, "last_login_at": iso(user.last_login_at), "membership_id": membership.id})
    return out


@router.post("/members", status_code=201)
def add_member(payload: MemberInvite, ctx: Ctx = Depends(get_ctx)):
    if ctx.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only an owner or admin can add team members.")
    if ctx.account_type != "business":
        raise HTTPException(status_code=400, detail="Creator accounts are single-seat. Upgrade to a business plan for a team.")

    usage = plans.usage(ctx.db, ctx.org)
    if usage["seats_used"] >= usage["seats_limit"]:
        raise HTTPException(
            status_code=402,
            detail=f"Your {usage['plan_name']} plan includes {usage['seats_limit']} seats. Upgrade to add more people.",
        )

    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))

    email = payload.email.strip().lower()
    if ctx.db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="That email already has an account.")

    user = User(
        email=email,
        name=payload.name.strip(),
        avatar_initials=initials(payload.name),
        password_hash=hash_password(payload.password),
        account_type="business",
    )
    ctx.db.add(user)
    ctx.db.flush()
    ctx.db.add(Membership(org_id=ctx.org.id, user_id=user.id, role=payload.role))
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            actor=ctx.user.name,
            action="member.added",
            object_type="user",
            object_ref=user.id,
            detail={"role": payload.role, "email": email},
        )
    )
    mail.deliver(
        ctx.db,
        email,
        f"You have been added to {ctx.org.name} on BrandSetGo",
        mail.invite_body(payload.name.strip(), ctx.org.name, email, payload.password, payload.role),
        kind="invite",
    )
    ctx.db.commit()
    return {**user_brief(user), "role": payload.role}


@router.patch("/members/{membership_id}")
def update_member(membership_id: str, payload: MemberRoleUpdate, ctx: Ctx = Depends(get_ctx)):
    if ctx.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only an owner or admin can change roles.")
    membership = ctx.db.get(Membership, membership_id)
    if membership is None or membership.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Member not found.")
    if membership.user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role.")
    membership.role = payload.role
    ctx.db.commit()
    return {"id": membership.id, "role": membership.role}


@router.delete("/members/{membership_id}")
def remove_member(membership_id: str, ctx: Ctx = Depends(get_ctx)):
    if ctx.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only an owner or admin can remove members.")
    membership = ctx.db.get(Membership, membership_id)
    if membership is None or membership.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Member not found.")
    if membership.user_id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You cannot remove yourself.")
    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Transfer ownership before removing the owner.")
    ctx.db.delete(membership)
    ctx.db.commit()
    return {"ok": True}


@router.get("/activity")
def activity(limit: int = 40, ctx: Ctx = Depends(get_ctx)):
    rows = list(
        ctx.db.scalars(
            select(AuditEvent).where(AuditEvent.org_id == ctx.org.id).order_by(AuditEvent.created_at.desc()).limit(limit)
        )
    )
    return [
        {"id": r.id, "action": r.action, "actor": r.actor, "at": iso(r.created_at), "detail": r.detail or {}}
        for r in rows
    ]
