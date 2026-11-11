"""Self-serve plan changes and invoices."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Ctx, get_ctx
from app.api.serialize import iso
from app.schemas import CheckoutRequest
from app.services import billing, plans

router = APIRouter(prefix="/billing", tags=["billing"])


def _invoice_row(inv) -> dict:
    return {
        "id": inv.id,
        "number": inv.number,
        "plan_from": inv.plan_from,
        "plan_to": inv.plan_to,
        "amount_inr": inv.amount_inr,
        "status": inv.status,
        "mode": inv.mode,
        "note": inv.note,
        "created_at": iso(inv.created_at),
        "created_by": inv.created_by,
    }


@router.get("/plans")
def list_plans(account_type: str | None = None):
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


@router.get("/summary")
def summary(ctx: Ctx = Depends(get_ctx)):
    usage = plans.usage(ctx.db, ctx.org)
    current = plans.get(ctx.org.plan) or {}
    return {
        "current": {
            "code": ctx.org.plan,
            "name": usage["plan_name"],
            "price_inr": current.get("price_inr"),
            "interval": current.get("interval"),
        },
        "usage": usage,
        "available": [
            p
            for p in plans.for_account(ctx.org.account_type)
            if p["code"] != ctx.org.plan
        ],
        "invoices": [_invoice_row(i) for i in billing.invoices(ctx.db, ctx.org.id)],
        "mode": "test",
        "note": "Test-mode billing: the plan change and invoice are recorded, no card is charged.",
    }


@router.post("/checkout")
def checkout(payload: CheckoutRequest, ctx: Ctx = Depends(get_ctx)):
    ctx.require("owner")
    try:
        invoice = billing.checkout(ctx.db, ctx.org, payload.plan, ctx.user.name)
    except billing.BillingError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {
        "invoice": _invoice_row(invoice),
        "plan": ctx.org.plan,
        "usage": plans.usage(ctx.db, ctx.org),
        "message": f"Switched to {plans.get(ctx.org.plan)['name']}. Invoice {invoice.number} recorded.",
    }
