from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import iso
from app.models import AIDisclosure, Brand, ContentVersion, Product, ReviewRun
from app.services import privacy

router = APIRouter(prefix="/privacy", tags=["privacy"])


class PreviewRequest(BaseModel):
    text: str
    sensitivity: str = "internal"
    brand_id: str | None = None


@router.get("/disclosures")
def disclosures(limit: int = 50, ctx: Ctx = Depends(get_ctx)):
    rows = list(
        ctx.db.scalars(
            select(AIDisclosure)
            .where(AIDisclosure.org_id == ctx.org.id)
            .order_by(AIDisclosure.created_at.desc())
            .limit(limit)
        )
    )
    return [
        {
            "id": r.id,
            "review_id": r.review_run_id,
            "created_at": iso(r.created_at),
            "processor": r.processor,
            "model": r.model,
            "region": r.region,
            "sensitivity": r.sensitivity,
            "data_categories": r.data_categories or [],
            "redaction_version": r.redaction_version,
            "purpose": r.purpose,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "calls": r.calls,
            "latency_ms": r.latency_ms,
            "retention": r.retention,
            "outcome": r.outcome,
        }
        for r in rows
    ]


@router.get("/summary")
def summary(ctx: Ctx = Depends(get_ctx)):
    rows = list(ctx.db.scalars(select(AIDisclosure).where(AIDisclosure.org_id == ctx.org.id)))
    labels = Counter(r.sensitivity for r in rows)
    return {
        "labels": [{"label": k, "count": v} for k, v in labels.most_common()],
        "policy": [
            {"label": k, **v} for k, v in privacy.POLICY_BY_SENSITIVITY.items()
        ],
        "total_transfers": len([r for r in rows if "no transfer" not in (r.region or "")]),
        "local_only": len([r for r in rows if "no transfer" in (r.region or "")]),
        "note": "Never claim zero exposure when external inference is used.",
    }


@router.post("/preview")
def preview(payload: PreviewRequest, ctx: Ctx = Depends(get_ctx)):
    products: list[Product] = []
    if payload.brand_id:
        brand = ctx.db.get(Brand, payload.brand_id)
        if brand and brand.org_id == ctx.org.id:
            products = [
                p
                for p in ctx.db.scalars(select(Product).where(Product.brand_id == brand.id))
                if p.is_confidential
            ]
    classification = privacy.classify(payload.text, payload.sensitivity, products)
    redacted, redaction_map = privacy.redact(payload.text, classification["detections"])
    return {
        "declared": classification["declared"],
        "effective": classification["effective"],
        "detections": classification["detections"],
        "redacted_text": redacted,
        "redaction_map": redaction_map,
        "policy": classification["policy"],
        "needs_local_processing": privacy.needs_local_processing(
            classification, classification["detections"]
        ),
    }
