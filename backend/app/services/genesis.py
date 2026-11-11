"""Brand Genesis: draft Brand DNA rules, then require owner approval.

Model-proposed rules are never authoritative on their own; publish_policy is
the only path that makes a rule enforceable.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, BrandRule, PolicyVersion, utcnow
from app.services import passport
from app.schemas import RuleDraft

STARTER_RULES: list[dict] = [
    {
        "code": "R-01",
        "title": "No unsubstantiated performance claims",
        "category": "claims",
        "statement": "Duration, efficacy and clinical claims must cite an approved claim record with a source document.",
        "severity": "high",
        "evidence_ref": "Approved claims registry",
    },
    {
        "code": "R-02",
        "title": "Product facts must match the product sheet",
        "category": "facts",
        "statement": "Sizes, quantities, ingredients and prices must match the current product sheet.",
        "severity": "medium",
        "evidence_ref": "Product catalogue",
    },
    {
        "code": "R-03",
        "title": "Brand voice and restricted language",
        "category": "tone",
        "statement": "Copy stays in the approved register and avoids the restricted-language list.",
        "severity": "high",
        "evidence_ref": "Brand voice guidelines",
    },
    {
        "code": "R-04",
        "title": "Logo, palette and layout",
        "category": "visual",
        "statement": "Only approved assets, palette colours and logo lockups may be used.",
        "severity": "medium",
        "evidence_ref": "Asset library",
    },
    {
        "code": "R-05",
        "title": "Accessibility minimums",
        "category": "accessibility",
        "statement": "Body text meets 4.5:1 contrast and every image carries alternative text.",
        "severity": "medium",
        "evidence_ref": "WCAG 2.1 AA",
    },
    {
        "code": "R-06",
        "title": "Approved terminology across languages",
        "category": "language",
        "statement": "English, Hindi and Marathi variants use glossary-approved product terms and keep disclaimers intact.",
        "severity": "high",
        "evidence_ref": "Brand glossary",
    },
]


def starter_rules(brand: Brand) -> list[RuleDraft]:
    """Draft a starter policy from the questionnaire, before any human approval."""
    sector = (brand.sector or "").lower()
    drafts: list[RuleDraft] = []
    for r in STARTER_RULES:
        if r["category"] == "language" and len(brand.languages or []) < 2:
            continue
        severity = r["severity"]
        if r["category"] == "claims" and sector in {"perfume", "skincare", "cosmetics", "beauty"}:
            severity = "high"
        drafts.append(
            RuleDraft(
                code=r["code"],
                title=r["title"],
                category=r["category"],
                statement=r["statement"],
                severity=severity,
                scope=list(brand.channels or []),
                source_ref="Brand Genesis starter set",
                evidence_ref=r["evidence_ref"],
            )
        )
    if sector in {"perfume", "skincare", "cosmetics", "beauty"}:
        drafts.append(
            RuleDraft(
                code="R-07",
                title="No therapeutic claims on cosmetic products",
                category="claims",
                statement="Cosmetic products may not claim to cure, treat or prevent conditions.",
                severity="critical",
                scope=list(brand.channels or []),
                source_ref="Brand Genesis starter set",
                evidence_ref="Cosmetics labelling guidance",
            )
        )
    return drafts


def create_policy(db: Session, brand: Brand, drafts: list[RuleDraft], source_summary: str = "") -> PolicyVersion:
    latest = db.scalars(
        select(PolicyVersion).where(PolicyVersion.brand_id == brand.id).order_by(PolicyVersion.version.desc())
    ).first()
    version = PolicyVersion(
        brand_id=brand.id,
        version=(latest.version + 1) if latest else 1,
        status="draft",
        source_summary=source_summary or "Brand Genesis starter set",
    )
    db.add(version)
    db.flush()
    for d in drafts:
        db.add(
            BrandRule(
                policy_version_id=version.id,
                code=d.code,
                title=d.title,
                category=d.category,
                statement=d.statement,
                severity=d.severity,
                scope=d.scope,
                source_ref=d.source_ref,
                evidence_ref=d.evidence_ref,
                is_authoritative=False,
                proposed_by_model=True,
                valid_from=utcnow(),
            )
        )
    db.flush()
    db.refresh(version)
    return version


def publish_policy(db: Session, brand: Brand, version: PolicyVersion, approver: str, rule_codes: list[str] | None = None) -> PolicyVersion:
    for r in version.rules:
        if rule_codes and r.code not in rule_codes:
            continue
        r.is_authoritative = True
    version.status = "published"
    version.approved_by = approver
    version.approved_at = utcnow()
    for older in brand.policy_versions:
        if older.id != version.id and older.status == "published":
            older.status = "superseded"
    db.flush()
    # a new policy invalidates clearances issued under the old one
    passport.invalidate_for_policy(db, brand.id, version.version, version.id)
    return version
