"""Demo dataset.

Everything here is executed for real through the review pipeline; the brands
and the history are labelled as sample data in the UI, exactly as the blueprint
asks. Nothing is hard-coded as a fake score.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Approval,
    ApprovedClaim,
    Asset,
    Brand,
    ContentItem,
    ContentVersion,
    GlossaryTerm,
    Membership,
    Organization,
    PolicyVersion,
    Product,
    ReviewRun,
    RiskPolicy,
    User,
    utcnow,
)
from app.services import genesis, passport
from app.services.reviews import content_hash, revise_content, run_review


def _policy(db: Session, brand: Brand, target_version: int) -> PolicyVersion:
    for v in range(1, target_version):
        db.add(
            PolicyVersion(
                brand_id=brand.id,
                version=v,
                status="superseded",
                source_summary="Earlier published policy",
                approved_by="Ananya Rao",
                approved_at=utcnow(),
            )
        )
    db.flush()
    version = genesis.create_policy(db, brand, genesis.starter_rules(brand), "Brand guidelines v1 + product sheets")
    version.version = target_version
    db.flush()
    return genesis.publish_policy(db, brand, version, "Ananya Rao")


def _content(db: Session, brand: Brand, user: User, **kw) -> ContentVersion:
    item = ContentItem(
        org_id=brand.org_id,
        brand_id=brand.id,
        title=kw["title"],
        channel=kw.get("channel", "instagram_caption"),
        language=kw.get("language", "en"),
        campaign=kw.get("campaign", ""),
        desired_cta=kw.get("desired_cta", ""),
        audience=kw.get("audience", brand.audience),
        modality=kw.get("modality", "text"),
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    version = ContentVersion(
        content_item_id=item.id,
        brand_id=brand.id,
        version=kw.get("version", 1),
        body_text=kw["body_text"],
        media_ref=kw.get("media_ref", ""),
        content_hash=content_hash(kw["body_text"], kw.get("media_ref", "")),
        sensitivity=kw.get("sensitivity", "internal"),
        meta=kw.get("meta", {}),
        author_id=user.id,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    return version


async def seed_demo(db: Session) -> dict:
    if db.scalars(select(Organization)).first():
        return {"seeded": False, "reason": "database already populated"}

    org = Organization(name="BrandSetGo Demo Studio", slug="brandsetgo-demo", plan="business")
    db.add(org)
    db.flush()

    owner = User(email="spparshm@gmail.com", name="Spparsh Mansuke", avatar_initials="SM")
    manager = User(email="ananya.rao@example.com", name="Ananya Rao", avatar_initials="AR")
    legal = User(email="vikram.shah@example.com", name="Vikram Shah", avatar_initials="VS")
    creator = User(email="meera.iyer@example.com", name="Meera Iyer", avatar_initials="MI")
    db.add_all([owner, manager, legal, creator])
    db.flush()
    for user, role in ((owner, "owner"), (manager, "manager"), (legal, "legal"), (creator, "creator")):
        db.add(Membership(org_id=org.id, user_id=user.id, role=role))
    db.flush()

    # ---------------------------------------------------------------- brands
    skincare = Brand(
        org_id=org.id,
        name="Sample Skincare Co.",
        kind="business",
        sector="skincare",
        description="Clinical-adjacent skincare for Indian skin, sold direct to consumer.",
        audience="Adults 25–40, India",
        tone="Warm, precise, never over-promising",
        languages=["en", "hi"],
        channels=["instagram_caption", "product_page", "website_banner"],
        personality={
            "banned_terms": ["cheap", "miracle"],
            "voice_keywords": ["skin", "daily", "smooth"],
            "approved_examples": [
                "Winter care, without the fuss. Our serum helps skin look smoother with daily use.",
                "Small rituals, visible comfort. Meet the night cream your skin asks for.",
            ],
        },
        palette={"colors": ["#2F4A3A", "#FFFDF7", "#A9812F", "#DDE9D8"], "text": "#2F4A3A", "background": "#FFFDF7"},
        logo_url="/brands/skincare-logo.svg",
        trust_score=0.74,
        owner_id=owner.id,
        is_sample=True,
    )
    perfume = Brand(
        org_id=org.id,
        name="Sample Perfume Line",
        kind="business",
        sector="perfume",
        description="Festive fragrance house with gift-led campaigns.",
        audience="Gift buyers 22–45, India",
        tone="Festive, generous, sensory",
        languages=["en", "mr"],
        channels=["website_banner", "instagram_caption"],
        personality={"banned_terms": ["sasta"], "approved_examples": ["The festive edit, boxed and ready."]},
        palette={"colors": ["#5A2A4A", "#FFFDF7", "#C9A227"], "text": "#5A2A4A", "background": "#FFFDF7"},
        logo_url="/brands/perfume-logo.svg",
        trust_score=0.68,
        owner_id=owner.id,
        is_sample=True,
    )
    personal = Brand(
        org_id=org.id,
        name="My Personal Brand",
        kind="personal",
        sector="design",
        description="Independent designer writing about brand systems.",
        audience="Founders and design leads",
        tone="Plain, generous, practical",
        languages=["en"],
        channels=["linkedin_post", "instagram_caption"],
        personality={"banned_terms": ["guru", "hack"], "approved_examples": ["Listen first, then design."]},
        palette={"colors": ["#1B2A21", "#FFFDF7"], "text": "#1B2A21", "background": "#FFFDF7"},
        logo_url="/brands/personal-mark.svg",
        trust_score=0.81,
        owner_id=owner.id,
        is_sample=True,
    )
    elan = Brand(
        org_id=org.id,
        name="Élan Fragrances",
        kind="business",
        sector="perfume",
        description="Small-batch Indian fragrance house launching its first oud line.",
        audience="Fragrance lovers 24–40, India",
        tone="Confident, sensory, restrained",
        languages=["en", "hi", "mr"],
        channels=["instagram_caption", "website_banner", "product_page"],
        personality={
            "banned_terms": ["cheap", "knockoff"],
            "voice_keywords": ["oud", "trail", "evening"],
            "approved_examples": ["An oud that stays close. Worn for evenings that matter."],
        },
        palette={"colors": ["#2C3A2E", "#F3E9D2", "#A9812F"], "text": "#2C3A2E", "background": "#F3E9D2"},
        logo_url="/brands/elan-logo.svg",
        trust_score=0.66,
        owner_id=owner.id,
        is_sample=True,
    )
    db.add_all([skincare, perfume, personal, elan])
    db.flush()

    for brand, version in ((skincare, 5), (perfume, 2), (personal, 1), (elan, 2)):
        _policy(db, brand, version)
        db.add(RiskPolicy(brand_id=brand.id))
    db.flush()

    # -------------------------------------------------------------- products
    serum = Product(
        brand_id=skincare.id,
        name="Winter Serum",
        sku="SK-WS-30",
        attributes={"volume_ml": 30, "price_inr": 899},
        sheet_ref="Product sheet v4",
        sheet_page=2,
    )
    night = Product(
        brand_id=skincare.id,
        name="Night Cream",
        sku="SK-NC-50",
        attributes={"volume_ml": 50, "price_inr": 1199},
        sheet_ref="Product sheet v4",
        sheet_page=3,
    )
    giftset = Product(
        brand_id=perfume.id,
        name="Diwali Gift Set",
        sku="PF-DG-01",
        attributes={"price_inr": 2499},
        sheet_ref="Festive catalogue 2026",
        sheet_page=1,
    )
    noir = Product(
        brand_id=elan.id,
        name="Noir Oud Eau de Parfum",
        sku="EL-NO-50",
        attributes={"volume_ml": 50, "price_inr": 4200},
        sheet_ref="Product sheet v4",
        sheet_page=2,
    )
    db.add_all([serum, night, giftset, noir])
    db.flush()

    db.add_all(
        [
            ApprovedClaim(
                brand_id=skincare.id,
                product_id=serum.id,
                text="Helps skin look smoother with daily use",
                evidence_ref="Clinical dossier CD-112, page 4",
            ),
            ApprovedClaim(
                brand_id=skincare.id,
                product_id=night.id,
                text="Suitable for daily use on all skin types",
                evidence_ref="Dermatology report DR-09",
            ),
            ApprovedClaim(
                brand_id=perfume.id,
                product_id=giftset.id,
                text="Festive gift box with two 10 ml travel sprays",
                evidence_ref="Festive catalogue 2026, page 1",
            ),
            ApprovedClaim(
                brand_id=elan.id,
                product_id=noir.id,
                text="Concentrated oud accord",
                evidence_ref="Fragrance brief FB-07",
            ),
        ]
    )

    for brand, count, prefix in ((skincare, 6, "skincare"), (perfume, 4, "perfume"), (personal, 2, "personal"), (elan, 3, "elan")):
        for i in range(1, count + 1):
            db.add(
                Asset(
                    brand_id=brand.id,
                    name=f"{prefix}-asset-{i}.png",
                    kind="image",
                    content_hash=f"{prefix}-h{i}",
                    palette=brand.palette.get("colors", [])[:2],
                    has_logo=True,
                    alt_text=f"{brand.name} campaign visual {i}" if i % 2 else "",
                )
            )

    db.add_all(
        [
            GlossaryTerm(
                brand_id=elan.id,
                term_en="long-lasting",
                term_hi="लंबे समय तक चलने वाला",
                term_mr="दीर्घकाळ टिकणारा",
                prohibited=["लम्बा चलने वाला"],
                notes="Use the approved Hindi/Marathi phrasing for duration.",
            ),
            GlossaryTerm(
                brand_id=elan.id,
                term_en="Eau de Parfum",
                term_hi="ओ डी पार्फ़्यूम",
                term_mr="ओ द पार्फ्युम",
                prohibited=["परफ्यूम वॉटर"],
                notes="Never translate the concentration name.",
            ),
            GlossaryTerm(
                brand_id=perfume.id,
                term_en="Diwali Gift Set",
                term_hi="दिवाली गिफ्ट सेट",
                term_mr="दिवाळी गिफ्ट सेट",
                prohibited=["दिवाली पैक"],
            ),
            GlossaryTerm(
                brand_id=skincare.id,
                term_en="Winter Serum",
                term_hi="विंटर सीरम",
                term_mr="विंटर सीरम",
                prohibited=["विंटर सीरम स्पेशल"],
            ),
        ]
    )
    db.commit()

    # --------------------------------------------------------- live reviews
    caption = _content(
        db,
        skincare,
        creator,
        title="Instagram caption – Winter serum",
        body_text="Meet our new Winter Serum, 50 ml. Clinically proven to remove wrinkles in 7 days. Shop now!",
        channel="instagram_caption",
        desired_cta="Shop now",
        audience="Adults 25–40, India",
        sensitivity="internal",
        meta={"contrast_ratio": 5.1},
    )
    first = await run_review(db, caption, creator.name)
    for patch in first.patches:
        patch.decision = "accepted"
        patch.decided_by = creator.name
        patch.decided_at = utcnow()
    db.commit()
    revised = revise_content(db, first, creator.name)
    second = await run_review(db, revised, creator.name)
    db.add(
        Approval(
            review_run_id=second.id,
            requested_by=creator.name,
            approver_role="manager",
            status="pending",
        )
    )

    banner = _content(
        db,
        perfume,
        creator,
        title="Website banner – Diwali offer",
        body_text="Diwali Gift Set: 20% off all festive gift boxes from 1 October. Shop the festive edit.",
        channel="website_banner",
        desired_cta="Shop the festive edit",
        meta={"contrast_ratio": 5.2},
    )
    banner_run = await run_review(db, banner, creator.name)
    db.add(
        Approval(
            review_run_id=banner_run.id,
            requested_by=creator.name,
            approver_role="owner",
            status="approved",
            decided_by="Ananya Rao",
            decided_at=utcnow(),
            comment="Festive campaign checked against catalogue.",
        )
    )
    passport.issue(db, banner_run, banner, perfume.current_policy, "Ananya Rao")

    cream = _content(
        db,
        skincare,
        creator,
        title="Product page – Night cream",
        body_text="Night Cream 50 ml cures eczema in 7 days. Guaranteed results. Buy now.",
        channel="product_page",
        desired_cta="Buy now",
    )
    await run_review(db, cream, creator.name)

    oud = _content(
        db,
        elan,
        creator,
        title="Instagram caption – Noir Oud",
        body_text="Noir Oud Eau de Parfum 50 ml lasts 24 hours. A deep oud trail. Shop the collection.",
        channel="instagram_caption",
        desired_cta="Shop the collection",
        audience="Fragrance lovers 24–40, India",
        meta={"contrast_ratio": 3.1},
    )
    await run_review(db, oud, creator.name)

    marathi = _content(
        db,
        elan,
        creator,
        title="Instagram caption – Noir Oud (Marathi)",
        body_text="नोअर ओउद परफ्यूम वॉटर — लम्बा चलने वाला सुगंध. आजच खरेदी करा.",
        channel="instagram_caption",
        language="mr",
        desired_cta="आजच खरेदी करा",
        meta={"variant_of": "en", "disclaimer_required": True, "disclaimer_present": False},
    )
    await run_review(db, marathi, creator.name)

    # Implied promise: no cue word a regex could catch, so only the semantic
    # reviewer sees it. This is the AI layer earning its place.
    teaser = _content(
        db,
        skincare,
        creator,
        title="Instagram caption – Winter serum teaser",
        body_text="Your skin will thank you in a week. No more dry patches. Shop the launch.",
        channel="instagram_caption",
        desired_cta="Shop the launch",
        meta={"contrast_ratio": 5.2},
    )
    await run_review(db, teaser, creator.name)

    notes = _content(
        db,
        personal,
        creator,
        title="LinkedIn post – studio notes",
        body_text="Three lessons from redesigning a 20-year-old family brand: listen first, cut the logo down, keep the promise. Read the notes.",
        channel="linkedin_post",
        desired_cta="Read the notes",
    )
    notes_run = await run_review(db, notes, creator.name)
    db.add(
        Approval(
            review_run_id=notes_run.id,
            requested_by=creator.name,
            approver_role=notes_run.routing.get("approver_role", "owner"),
            status="pending",
        )
    )
    db.commit()

    return {"seeded": True, "brands": 4, "reviews": 8}
