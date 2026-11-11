"""Self-serve plan changes.

Test-mode billing: no card is charged, but the subscription change, the invoice
record and the audit entry are real, so the pricing model is exercised end to
end instead of dead-ending on a 402.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Invoice, Organization
from app.services import plans


class BillingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _next_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = len(list(db.scalars(select(Invoice.id)))) + 1
    return f"BSP-INV-{year}-{count:04d}"


def invoices(db: Session, org_id: str) -> list[Invoice]:
    return list(
        db.scalars(select(Invoice).where(Invoice.org_id == org_id).order_by(Invoice.created_at.desc()))
    )


def checkout(db: Session, org: Organization, plan_code: str, actor: str) -> Invoice:
    plan = plans.get(plan_code)
    if plan is None:
        raise BillingError("Unknown plan.")
    if plan["account_type"] != org.account_type:
        raise BillingError(
            f"{plan['name']} is a {plan['account_type']} plan and this workspace is {org.account_type}.",
            status=409,
        )
    if plan_code == org.plan:
        raise BillingError("That is already your current plan.", status=409)

    usage = plans.usage(db, org)
    notes = []
    if usage["reviews_used"] > plan["reviews_per_month"]:
        notes.append("usage already above the new monthly limit")
    if usage["seats_used"] > plan["seats"]:
        notes.append(f"{usage['seats_used']} seats in use, new plan includes {plan['seats']}")
    if usage["brands_used"] > plan["brands"]:
        notes.append(f"{usage['brands_used']} brands in use, new plan includes {plan['brands']}")

    amount = int(plan.get("price_inr") or 0)
    invoice = Invoice(
        org_id=org.id,
        number=_next_number(db),
        plan_from=org.plan,
        plan_to=plan_code,
        amount_inr=amount,
        status="paid" if amount == 0 else "paid",
        mode="test",
        created_by=actor,
        note="; ".join(notes)[:240],
    )
    db.add(invoice)

    previous = org.plan
    org.plan = plan_code
    org.seats = plan["seats"]
    db.add(
        AuditEvent(
            org_id=org.id,
            actor=actor,
            action="billing.plan_changed",
            object_type="organization",
            object_ref=org.id,
            detail={"from": previous, "to": plan_code, "amount_inr": amount, "invoice": invoice.number, "mode": "test"},
        )
    )
    db.commit()
    db.refresh(invoice)
    return invoice
