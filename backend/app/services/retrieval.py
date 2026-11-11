"""Tenant-scoped retrieval of everything a review is allowed to use."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovedClaim, Asset, Brand, BrandRule, GlossaryTerm, PolicyVersion, Product


def brand_for(db: Session, brand_id: str, org_id: str) -> Brand | None:
    brand = db.get(Brand, brand_id)
    if brand is None or brand.org_id != org_id:
        return None
    return brand


def current_policy(db: Session, brand: Brand) -> PolicyVersion | None:
    """The enforced policy, if the owner has published one."""
    return brand.current_policy


def reviewable_policy(db: Session, brand: Brand) -> PolicyVersion | None:
    """What a review is judged against: published if it exists, otherwise the latest draft.

    A brand must never be unable to check its content just because the policy is
    still a draft. A draft review is labelled as provisional in the result, so the
    difference between "checked" and "enforceable" stays visible.
    """
    published = brand.current_policy
    if published is not None:
        return published
    if brand.policy_versions:
        return max(brand.policy_versions, key=lambda p: p.version)
    return None


def rules_for(db: Session, policy: PolicyVersion | None, channel: str) -> list[BrandRule]:
    if policy is None:
        return []
    # published policies only expose authoritative rules; a draft has none, so fall
    # back to its proposed rules and let the review mark them as provisional
    authoritative = [r for r in policy.rules if r.is_authoritative] or list(policy.rules)
    return [r for r in authoritative if not r.scope or channel in r.scope] or authoritative


def claims_for(db: Session, brand_id: str) -> list[ApprovedClaim]:
    return list(db.scalars(select(ApprovedClaim).where(ApprovedClaim.brand_id == brand_id)))


def products_for(db: Session, brand_id: str) -> list[Product]:
    return list(db.scalars(select(Product).where(Product.brand_id == brand_id)))


def assets_for(db: Session, brand_id: str) -> list[Asset]:
    return list(db.scalars(select(Asset).where(Asset.brand_id == brand_id)))


def glossary_for(db: Session, brand_id: str) -> list[GlossaryTerm]:
    return list(db.scalars(select(GlossaryTerm).where(GlossaryTerm.brand_id == brand_id)))
