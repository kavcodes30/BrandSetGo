"""Plan catalogue and usage metering.

Plans are product configuration, not user data: one place to change pricing.
Usage is measured from real records so the admin dashboard shows live numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Brand, ContentItem, Membership, Organization, ReviewRun, User

PLANS: dict[str, dict] = {
    "creator_free": {
        "code": "creator_free",
        "name": "Creator Free",
        "account_type": "creator",
        "price_inr": 0,
        "interval": "month",
        "seats": 1,
        "brands": 1,
        "reviews_per_month": 20,
        "features": ["1 personal brand", "20 reviews / month", "AI classification", "legal flagging"],
        "blurb": "For a solo creator checking their own posts.",
    },
    "creator_pro": {
        "code": "creator_pro",
        "name": "Creator Pro",
        "account_type": "creator",
        "price_inr": 499,
        "interval": "month",
        "seats": 1,
        "brands": 3,
        "reviews_per_month": 300,
        "features": [
            "3 brands",
            "300 reviews / month",
            "video & audio transcript flags",
            "Brand Passport records",
            "creator coaching",
        ],
        "blurb": "For creators publishing daily across formats.",
    },
    "business_starter": {
        "code": "business_starter",
        "name": "Business Starter",
        "account_type": "business",
        "price_inr": 2499,
        "interval": "month",
        "seats": 5,
        "brands": 5,
        "reviews_per_month": 800,
        "features": [
            "5 brands",
            "5 team seats",
            "800 reviews / month",
            "approvals & routing",
            "privacy center & disclosures",
        ],
        "blurb": "For a small in-house marketing team.",
    },
    "business_growth": {
        "code": "business_growth",
        "name": "Business Growth",
        "account_type": "business",
        "price_inr": 7999,
        "interval": "month",
        "seats": 20,
        "brands": 25,
        "reviews_per_month": 4000,
        "features": [
            "25 brands",
            "20 team seats",
            "4000 reviews / month",
            "legal reviewer role",
            "analytics & audit export",
        ],
        "blurb": "For agencies and multi-brand teams.",
    },
    "enterprise": {
        "code": "enterprise",
        "name": "Enterprise",
        "account_type": "business",
        "price_inr": None,
        "interval": "custom",
        "seats": 100,
        "brands": 200,
        "reviews_per_month": 50000,
        "features": ["SSO", "self-hosted model option", "custom retention", "SLA & audit exports"],
        "blurb": "For regulated enterprises. Talk to us.",
    },
}

DEFAULT_PLAN = {"creator": "creator_free", "business": "business_starter"}


def get(code: str) -> dict | None:
    return PLANS.get(code)


def for_account(account_type: str) -> list[dict]:
    return [p for p in PLANS.values() if p["account_type"] == account_type]


def price_of(code: str) -> int:
    plan = PLANS.get(code) or {}
    return int(plan.get("price_inr") or 0)


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(db: Session, org: Organization) -> dict:
    plan = PLANS.get(org.plan) or PLANS[DEFAULT_PLAN.get(org.account_type, "business_starter")]
    month_start = _month_start()

    reviews_this_month = db.scalar(
        select(func.count(ReviewRun.id)).where(
            ReviewRun.org_id == org.id, ReviewRun.created_at >= month_start
        )
    ) or 0
    brands = db.scalar(select(func.count(Brand.id)).where(Brand.org_id == org.id)) or 0
    members = db.scalar(select(func.count(Membership.id)).where(Membership.org_id == org.id)) or 0
    content_items = db.scalar(select(func.count(ContentItem.id)).where(ContentItem.org_id == org.id)) or 0

    tokens_in = tokens_out = calls = 0
    for run in db.scalars(select(ReviewRun).where(ReviewRun.org_id == org.id, ReviewRun.created_at >= month_start)):
        meta = run.ai_meta or {}
        tokens_in += int(meta.get("tokens_in") or 0)
        tokens_out += int(meta.get("tokens_out") or 0)
        calls += int(meta.get("calls") or 0)

    return {
        "plan": plan["code"],
        "plan_name": plan["name"],
        "price_inr": plan["price_inr"],
        "reviews_used": reviews_this_month,
        "reviews_limit": plan["reviews_per_month"],
        "reviews_remaining": max(0, plan["reviews_per_month"] - reviews_this_month),
        "brands_used": brands,
        "brands_limit": plan["brands"],
        "seats_used": members,
        "seats_limit": plan["seats"],
        "content_items": content_items,
        "ai_calls": calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "period_start": month_start.isoformat(),
        "over_review_limit": reviews_this_month >= plan["reviews_per_month"],
    }


def quota_block_reason(db: Session, org: Organization) -> str | None:
    """Return an upgrade message when the workspace is out of review quota."""
    u = usage(db, org)
    if u["over_review_limit"]:
        return (
            f"Your {u['plan_name']} plan includes {u['reviews_limit']} reviews per month and this workspace "
            f"has used {u['reviews_used']}. Upgrade to keep reviewing this month."
        )
    return None


def can_add_brand(db: Session, org: Organization) -> bool:
    u = usage(db, org)
    return u["brands_used"] < u["brands_limit"]


def mrr_breakdown(orgs: list[Organization]) -> dict:
    """Monthly recurring revenue from live subscriptions (no trial maths)."""
    by_plan: dict[str, int] = {}
    mrr = 0
    for org in orgs:
        if org.status != "active":
            continue
        price = price_of(org.plan)
        if price:
            mrr += price
            by_plan[org.plan] = by_plan.get(org.plan, 0) + 1
    return {
        "mrr_inr": mrr,
        "arr_inr": mrr * 12,
        "by_plan": [{"plan": code, "count": count, "price_inr": price_of(code)} for code, count in by_plan.items()],
        "paying_orgs": sum(by_plan.values()),
    }
