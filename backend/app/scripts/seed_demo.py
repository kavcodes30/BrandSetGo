"""Create a demo workspace set with freshly generated passwords.

Nothing is hardcoded: the accounts, their passwords and their content are created
at run time, and the passwords are printed once. Use it to look around quickly,
or skip it and sign up normally.

    python -m app.scripts.seed_demo
"""
from __future__ import annotations

import asyncio
import secrets

from sqlalchemy import select

from app.core.db import SessionLocal, init_db
from app.models import ApprovedClaim, Brand, ContentItem, ContentVersion, GlossaryTerm, Product, User
from app.schemas import ContentCreate, SignupRequest
from app.services import auth as auth_svc
from app.services.reviews import content_hash, run_review


def _password() -> str:
    return "Bs" + secrets.token_urlsafe(9) + "7"


async def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(User)):
            print("This database already has accounts. Nothing to do.")
            print("Delete backend/brandsetgo.db (or run `run.bat reset`) to start fresh.")
            return

        admin_pw, biz_pw, creator_pw = _password(), _password(), _password()

        admin, _, _ = auth_svc.signup(
            db,
            SignupRequest(
                name="Platform Admin",
                email="admin@brandsetgo.local",
                password=admin_pw,
                account_type="business",
                company="BrandSetGo",
                plan="enterprise",
            ),
        )
        business, org, _ = auth_svc.signup(
            db,
            SignupRequest(
                name="Ananya Rao",
                email="ananya@elan.example",
                password=biz_pw,
                account_type="business",
                company="Élan Fragrances",
                plan="business_growth",
            ),
        )
        creator, creator_org, _ = auth_svc.signup(
            db,
            SignupRequest(
                name="Meera Iyer",
                email="meera@creator.example",
                password=creator_pw,
                account_type="creator",
                plan="creator_pro",
            ),
        )

        # ---- business brand with a published policy
        brand = Brand(
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
            owner_id=business.id,
            owner_user_id=business.id,
        )
        db.add(brand)
        db.flush()

        from app.services import genesis

        policy = genesis.create_policy(db, brand, genesis.starter_rules(brand), "Brand guidelines v1")
        genesis.publish_policy(db, brand, policy, business.name)

        product = Product(
            brand_id=brand.id,
            name="Noir Oud Eau de Parfum",
            sku="EL-NO-50",
            attributes={"volume_ml": 50, "price_inr": 4200},
            sheet_ref="Product sheet v4",
            sheet_page=2,
        )
        db.add(product)
        db.flush()
        db.add(ApprovedClaim(brand_id=brand.id, product_id=product.id, text="Concentrated oud accord", evidence_ref="Fragrance brief FB-07"))
        db.add_all([
            GlossaryTerm(brand_id=brand.id, term_en="long-lasting", term_hi="लंबे समय तक चलने वाला",
                         term_mr="दीर्घकाळ टिकणारा", prohibited=["लम्बा चलने वाला"]),
            GlossaryTerm(brand_id=brand.id, term_en="Eau de Parfum", term_hi="ओ डी पार्फ़्यूम",
                         term_mr="ओ द पार्फ्युम", prohibited=["परफ्यूम वॉटर"]),
        ])
        db.commit()

        # ---- content that exercises claims, legal and video paths
        def add(item_org_id: str, brand_id: str, author: str, **kw) -> ContentVersion:
            item = ContentItem(org_id=item_org_id, brand_id=brand_id, title=kw["title"],
                               channel=kw.get("channel", "instagram_caption"), language=kw.get("language", "en"),
                               desired_cta=kw.get("desired_cta", ""), audience=kw.get("audience", ""),
                               modality=kw.get("modality", "text"), created_by=author)
            db.add(item)
            db.flush()
            transcript = kw.get("transcript", [])
            body = kw.get("body_text") or "\n".join(s["text"] for s in transcript)
            version = ContentVersion(
                content_item_id=item.id, brand_id=brand_id, version=1, body_text=body,
                content_hash=content_hash(body), sensitivity=kw.get("sensitivity", "internal"),
                meta=kw.get("meta", {}), transcript=transcript,
                duration_s=float(max((s["end"] for s in transcript), default=0.0)), author_id=author,
            )
            db.add(version)
            db.flush()
            db.refresh(version)
            return version

        oud = add(org.id, brand.id, business.id,
                  title="Instagram caption – Noir Oud",
                  body_text="Noir Oud Eau de Parfum 50 ml lasts 24 hours. A deep oud trail. Shop the collection.",
                  desired_cta="Shop the collection", audience="Fragrance lovers 24–40, India")
        await run_review(db, oud, business.name)

        reel = add(org.id, brand.id, business.id,
                   title="Reel – 30s launch film",
                   modality="video",
                   channel="instagram_caption",
                   transcript=[
                       {"start": 0.0, "end": 3.2, "text": "Meet Noir Oud, our new evening fragrance."},
                       {"start": 3.2, "end": 7.8, "text": "Clinically proven to cure anxiety and help you sleep better."},
                       {"start": 7.8, "end": 12.0, "text": "Guaranteed to last 24 hours on every skin type."},
                       {"start": 12.0, "end": 16.5, "text": "Order today, only 100 bottles while stocks last."},
                   ])
        await run_review(db, reel, business.name)

        personal = db.scalar(select(Brand).where(Brand.org_id == creator_org.id))
        from app.services import genesis as genesis_svc

        personal_policy = personal.current_policy
        if personal_policy is None and personal.policy_versions:
            genesis_svc.publish_policy(db, personal, personal.policy_versions[-1], creator.name)
            db.commit()
        post = add(creator_org.id, personal.id, creator.id,
                   title="Instagram caption – gifted serum",
                   body_text="Loving this gifted serum from Glow Co — my sponsored collab. Cures acne in 7 days!",
                   desired_cta="Link in bio", audience="Skincare-curious followers")
        await run_review(db, post, creator.name)

        print("\nDemo accounts created (passwords shown once):\n")
        print(f"  platform admin : admin@brandsetgo.local   {admin_pw}")
        print(f"  business owner : ananya@elan.example      {biz_pw}")
        print(f"  creator        : meera@creator.example    {creator_pw}")
        print("\nSign in at the login page. Change the passwords after the demo.\n")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
