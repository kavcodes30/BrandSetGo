from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import brand_brief, brand_detail, glossary_row, iso, rule_row
from app.models import (
    ApprovedClaim,
    Asset,
    AuditEvent,
    Brand,
    ContentItem,
    ContentVersion,
    GlossaryTerm,
    Product,
    ReviewRun,
    RiskPolicy,
)
from app.schemas import (
    BrandCreate,
    ClaimCreate,
    GlossaryCreate,
    PolicyApprove,
    PolicyImport,
    ProductCreate,
    RiskPolicyUpdate,
    RuleDraft,
)
from app.services import coaching as coaching_svc
from app.services import ai_review, genesis, insights as insights_svc, plans


router = APIRouter(prefix="/brands", tags=["brands"])


def _brand_or_404(ctx: Ctx, brand_id: str) -> Brand:
    brand = ctx.db.get(Brand, brand_id)
    if brand is None or brand.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace.")
    return brand


@router.get("")
def list_brands(ctx: Ctx = Depends(get_ctx)):
    brands = list(ctx.db.scalars(select(Brand).where(Brand.org_id == ctx.org.id).order_by(Brand.created_at)))
    return [brand_brief(ctx.db, b) for b in brands]


@router.post("", status_code=201)
def create_brand(payload: BrandCreate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    if not plans.can_add_brand(ctx.db, ctx.org):
        usage = plans.usage(ctx.db, ctx.org)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Your {usage['plan_name']} plan includes {usage['brands_limit']} brand(s) and this "
                f"workspace already has {usage['brands_used']}. Upgrade to add another."
            ),
        )
    brand = Brand(
        org_id=ctx.org.id,
        name=payload.name,
        kind=payload.kind,
        sector=payload.sector,
        description=payload.description,
        audience=payload.audience,
        tone=payload.tone,
        languages=payload.languages,
        channels=payload.channels,
        personality=payload.personality,
        palette=payload.palette,
        logo_url=payload.logo_url,
        owner_id=ctx.user.id,
        owner_user_id=ctx.user.id,
    )
    ctx.db.add(brand)
    ctx.db.flush()
    drafts = genesis.starter_rules(brand)
    policy = genesis.create_policy(ctx.db, brand, drafts, "Brand Genesis starter set")
    ctx.db.add(RiskPolicy(brand_id=brand.id))
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=brand.id,
            actor=ctx.user.name,
            action="brand.created",
            object_type="brand",
            object_ref=brand.id,
            detail={"name": brand.name, "draft_policy": policy.version},
        )
    )
    ctx.db.commit()
    ctx.db.refresh(brand)
    return {
        "brand": brand_detail(ctx.db, brand),
        "draft_policy": {"id": policy.id, "version": policy.version, "rules": [rule_row(r) for r in policy.rules]},
    }


@router.get("/{brand_id}")
def get_brand(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    return brand_detail(ctx.db, _brand_or_404(ctx, brand_id))


@router.post("/{brand_id}/policies/import")
async def import_policy(brand_id: str, payload: PolicyImport, ctx: Ctx = Depends(get_ctx)):
    """Create a draft policy from supplied rules, pasted guidelines, or the starter set.

    Pasted guidelines go through Sarvam for extraction; the result is still a
    *draft* that an owner must approve before it can block anything.
    """
    ctx.require("creator")
    brand = _brand_or_404(ctx, brand_id)

    drafts = list(payload.rules)
    meta: dict = {"source": "supplied rules"}
    if not drafts and payload.guideline_text.strip():
        drafts, meta = await ai_review.extract_rules(
            payload.guideline_text,
            brand_name=brand.name,
            sector=brand.sector,
            channels=brand.channels or [],
        )
        meta["source"] = "sarvam extraction" if drafts else "starter set (extraction unavailable)"
    if not drafts:
        drafts = genesis.starter_rules(brand)
        meta.setdefault("source", "starter set")

    policy = genesis.create_policy(
        ctx.db, brand, drafts, payload.source_summary or meta["source"]
    )
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=brand.id,
            actor=ctx.user.name,
            action="policy.drafted",
            object_type="policy_version",
            object_ref=policy.id,
            detail={"rules": len(policy.rules), "source": meta["source"]},
        )
    )
    ctx.db.commit()
    return {
        "id": policy.id,
        "version": policy.version,
        "status": policy.status,
        "rules": [rule_row(r) for r in policy.rules],
        "extraction": meta,
    }


@router.post("/{brand_id}/policies/approve")
def approve_policy(brand_id: str, payload: PolicyApprove, ctx: Ctx = Depends(get_ctx)):
    ctx.require("manager")
    brand = _brand_or_404(ctx, brand_id)
    latest = max(brand.policy_versions, key=lambda p: p.version) if brand.policy_versions else None
    if latest is None:
        raise HTTPException(status_code=400, detail="No policy draft to approve.")
    if latest.status == "published":
        raise HTTPException(status_code=400, detail="This policy version is already published.")
    policy = genesis.publish_policy(ctx.db, brand, latest, payload.approver or ctx.user.name, payload.rule_codes or None)
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=brand.id,
            actor=ctx.user.name,
            action="policy.published",
            object_type="policy_version",
            object_ref=policy.id,
            detail={"version": policy.version, "rules": len(policy.rules)},
        )
    )
    ctx.db.commit()
    return {"id": policy.id, "version": policy.version, "status": policy.status, "rules": [rule_row(r) for r in policy.rules]}


@router.get("/{brand_id}/genesis")
def genesis_preview(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    brand = _brand_or_404(ctx, brand_id)
    drafts: list[RuleDraft] = genesis.starter_rules(brand)
    return {"rules": [d.model_dump() for d in drafts], "source": "Brand Genesis starter set"}


@router.post("/{brand_id}/products", status_code=201)
def add_product(brand_id: str, payload: ProductCreate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    brand = _brand_or_404(ctx, brand_id)
    product = Product(
        brand_id=brand.id,
        name=payload.name,
        sku=payload.sku,
        attributes=payload.attributes,
        sheet_ref=payload.sheet_ref,
        sheet_page=payload.sheet_page,
    )
    ctx.db.add(product)
    ctx.db.commit()
    return {"id": product.id, "name": product.name, "attributes": product.attributes}


@router.post("/{brand_id}/claims", status_code=201)
def add_claim(brand_id: str, payload: ClaimCreate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("manager")
    brand = _brand_or_404(ctx, brand_id)
    claim = ApprovedClaim(
        brand_id=brand.id,
        product_id=payload.product_id,
        text=payload.text,
        evidence_ref=payload.evidence_ref,
        status=payload.status,
    )
    ctx.db.add(claim)
    ctx.db.commit()
    return {"id": claim.id, "text": claim.text, "status": claim.status}


@router.get("/{brand_id}/glossary")
def get_glossary(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    brand = _brand_or_404(ctx, brand_id)
    return [glossary_row(g) for g in ctx.db.scalars(select(GlossaryTerm).where(GlossaryTerm.brand_id == brand.id))]


@router.post("/{brand_id}/glossary", status_code=201)
def add_glossary(brand_id: str, payload: GlossaryCreate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("manager")
    brand = _brand_or_404(ctx, brand_id)
    term = GlossaryTerm(
        brand_id=brand.id,
        term_en=payload.term_en,
        term_hi=payload.term_hi,
        term_mr=payload.term_mr,
        prohibited=payload.prohibited,
        notes=payload.notes,
    )
    ctx.db.add(term)
    ctx.db.commit()
    return glossary_row(term)


@router.put("/{brand_id}/risk-policy")
def update_risk_policy(brand_id: str, payload: RiskPolicyUpdate, ctx: Ctx = Depends(get_ctx)):
    ctx.require("manager")
    brand = _brand_or_404(ctx, brand_id)
    row = ctx.db.scalars(select(RiskPolicy).where(RiskPolicy.brand_id == brand.id)).first()
    if row is None:
        row = RiskPolicy(brand_id=brand.id)
        ctx.db.add(row)
    row.fast_track_max = payload.fast_track_max
    row.manager_max = payload.manager_max
    row.trust_floor = payload.trust_floor
    row.auto_clear_enabled = payload.auto_clear_enabled
    ctx.db.commit()
    return {
        "fast_track_max": row.fast_track_max,
        "manager_max": row.manager_max,
        "trust_floor": row.trust_floor,
        "auto_clear_enabled": row.auto_clear_enabled,
    }


@router.get("/{brand_id}/coaching")
def brand_coaching(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    brand = _brand_or_404(ctx, brand_id)
    return coaching_svc.summary(ctx.db, brand.id)


@router.get("/{brand_id}/insights")
def brand_insights(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    brand = _brand_or_404(ctx, brand_id)
    return insights_svc.brand_insights(ctx.db, brand.id)


@router.get("/{brand_id}/multilingual")
def multilingual(brand_id: str, ctx: Ctx = Depends(get_ctx)):
    """Compare the latest variant in each language against the glossary."""
    brand = _brand_or_404(ctx, brand_id)
    items = list(ctx.db.scalars(select(ContentItem).where(ContentItem.brand_id == brand.id)))
    glossary = list(ctx.db.scalars(select(GlossaryTerm).where(GlossaryTerm.brand_id == brand.id)))

    variants = []
    for item in items:
        version = max(item.versions, key=lambda v: v.version) if item.versions else None
        if version is None:
            continue
        run = ctx.db.scalars(
            select(ReviewRun)
            .where(ReviewRun.content_version_id == version.id)
            .order_by(ReviewRun.created_at.desc())
        ).first()
        prohibited_hits = [
            bad for g in glossary for bad in (g.prohibited or []) if bad and bad in version.body_text
        ]
        approved_used = [
            g.term_hi if item.language == "hi" else g.term_mr
            for g in glossary
            if (g.term_hi if item.language == "hi" else g.term_mr) in version.body_text
        ]
        variants.append(
            {
                "content_id": item.id,
                "title": item.title,
                "language": item.language,
                "body_text": version.body_text,
                "review_id": run.id if run else None,
                "status": run.status if run else "draft",
                "risk_score": run.risk_score if run else None,
                "prohibited_hits": prohibited_hits,
                "approved_terms_used": [t for t in approved_used if t],
                "disclaimer_present": (version.meta or {}).get("disclaimer_present", True),
            }
        )

    en_variants = [v for v in variants if v["language"] == "en"]
    return {
        "brand": {"id": brand.id, "name": brand.name, "languages": brand.languages or []},
        "variants": variants,
        "source_variant": en_variants[0]["title"] if en_variants else None,
        "checks": [
            "Glossary term used in every variant",
            "Prohibited translations absent",
            "Disclaimer survives translation",
            "Claims and quantities identical across variants",
        ],
    }
