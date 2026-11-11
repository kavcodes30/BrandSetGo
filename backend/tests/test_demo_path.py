"""The end-to-end path a paying customer takes, plus the legal escalations."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from conftest import PASSWORD, signup_ok, unique_email


def _business_with_brand(client) -> tuple[str, str]:
    data = signup_ok(client, account_type="business", name="Ananya Rao", email=unique_email("owner"),
                     company="Élan Fragrances", plan="business_growth")
    created = client.post(
        "/api/brands",
        json={
            "name": "Élan Fragrances",
            "kind": "business",
            "sector": "perfume",
            "audience": "Fragrance lovers 24-40, India",
            "tone": "Confident, sensory, restrained",
            "languages": ["en", "hi"],
            "channels": ["instagram_caption", "product_page"],
            "personality": {"banned_terms": ["cheap"], "approved_examples": ["An oud that stays close."]},
            "palette": {"colors": ["#2C3A2E", "#F3E9D2"], "text": "#2C3A2E", "background": "#F3E9D2"},
        },
    ).json()
    brand_id = created["brand"]["id"]
    client.post(f"/api/brands/{brand_id}/policies/approve", json={"approver": "Ananya Rao"})
    client.post(
        f"/api/brands/{brand_id}/products",
        json={"name": "Noir Oud Eau de Parfum", "attributes": {"volume_ml": 50}, "sheet_ref": "Product sheet v4", "sheet_page": 2},
    )
    client.post(f"/api/brands/{brand_id}/claims", json={"text": "Concentrated oud accord", "evidence_ref": "Brief FB-07"})
    return brand_id, data["org"]["id"]


def test_static_app_is_served_by_the_api(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "BrandSetGo" in index.text
    for asset in ("/css/app.css", "/js/app.js", "/js/core.js", "/js/views/review.js"):
        assert client.get(asset).status_code == 200, asset


def test_login_page_is_reachable_without_a_session(fresh):
    assert fresh.get("/").status_code == 200


def test_full_acceptance_path(client, admin_client):
    brand_id, _ = _business_with_brand(client)

    content = client.post(
        "/api/content",
        json={
            "brand_id": brand_id,
            "title": "Instagram caption - Noir Oud",
            "body_text": "Noir Oud Eau de Parfum 50 ml lasts 24 hours. Shop the collection.",
            "channel": "instagram_caption",
            "desired_cta": "Shop the collection",
            "audience": "Fragrance lovers 24-40, India",
        },
    ).json()

    review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()

    # claims and the legal registry both catch the duration promise
    claim = next(f for f in review["findings"] if f["agent"] == "claims" and f["status"] == "confirmed")
    assert "lasts 24 hours" in claim["span_text"].lower()
    legal = next(f for f in review["findings"] if f["guideline_code"] == "IN-ASCI-I4-DURATION")
    assert "Chapter I.4" in legal["guideline_citation"]
    assert legal["remediation"]
    assert review["disagreements"], "tone approval vs claims rejection stays visible"
    assert "legal" in review["completeness"]["returned"]

    # drift invariants are evaluated before anything is accepted
    assert review["drift"]["invariants"]
    patch = next(p for p in review["patches"] if "lasts" in p["original"].lower())
    assert patch["replacement"] == "long-lasting"

    decision = client.post(f"/api/rewrite-patches/{patch['id']}/decision", json={"decision": "accepted"}).json()
    assert decision["blocked"] is False
    drift = {c["key"]: c["passed"] for c in decision["drift"]["invariants"]}
    assert drift["cta_preserved"] and drift["audience_preserved"] and drift["key_facts_unchanged"]

    revised = client.post(f"/api/reviews/{review['id']}/revise").json()
    new_review = revised["review"]
    assert new_review["content"]["version"] == 2
    assert new_review["risk_score"] <= review["risk_score"]

    approval = client.post(f"/api/approvals?review_run_id={new_review['id']}", json={"approver_role": "manager"}).json()
    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "approved", "comment": "Safer wording, CTA intact."},
    ).json()
    assert decided["clearance_id"]

    passport = client.get(f"/api/passports/{decided['clearance_id']}").json()
    assert passport["content"]["version"] == 2
    assert passport["policy_version"] == 1
    assert passport["decision"]["status"] == "approved"

    disclosures = client.get("/api/privacy/disclosures").json()
    assert any(d["review_id"] == new_review["id"] for d in disclosures)

    client.post(f"/api/content/{content['id']}/versions", json={"body_text": "Noir Oud 50 ml. Shop."})
    assert client.get(f"/api/verify/{decided['clearance_id']}").json()["valid"] is False


def test_critical_claim_blocks_and_escalates_to_legal(client, admin_client):
    brand_id, _ = _business_with_brand(client)
    content = client.post(
        "/api/content",
        json={
            "brand_id": brand_id,
            "title": "Product page - night cream",
            "body_text": "Our night cream cures eczema in 7 days. Guaranteed results.",
            "channel": "product_page",
        },
    ).json()
    review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()

    assert review["hard_blocker"] is True
    assert review["routing"]["route"] == "legal"
    critical = [f for f in review["findings"] if f["severity"] == "critical"]
    assert critical
    dmr = next(f for f in review["findings"] if f["guideline_code"] == "IN-DMR-S3")
    assert dmr["guideline_authority"].startswith("Drugs and Magic Remedies")
    assert dmr["legal_basis"]

    # approval is refused while the blocker stands
    approval = client.post(f"/api/approvals?review_run_id={review['id']}", json={"approver_role": "legal"})
    assert approval.status_code == 201
    blocked = client.post(
        f"/api/approvals/{approval.json()['id']}/decision", json={"decision": "approved", "comment": "ship it"}
    )
    assert blocked.status_code == 409


def test_override_needs_the_legal_role_and_a_reason(client, admin_client):
    brand_id, _ = _business_with_brand(client)
    content = client.post(
        "/api/content",
        json={"brand_id": brand_id, "title": "cure copy", "body_text": "Cures insomnia overnight.", "channel": "instagram_caption"},
    ).json()
    review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
    assert review["hard_blocker"] is True

    # owner cannot override without a written justification
    assert client.post(f"/api/reviews/{review['id']}/override?justification=%20").status_code == 400

    # a member with the creator role cannot override at all
    email = unique_email("creator-role")
    client.post(
        "/api/workspace/members",
        json={"name": "Junior Creator", "email": email, "password": PASSWORD, "role": "creator"},
    )
    with TestClient(app) as junior:
        assert junior.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        denied = junior.post(f"/api/reviews/{review['id']}/override?justification=because")
        assert denied.status_code == 403

    # a legal reviewer can, and it lands in the audit trail
    legal_email = unique_email("legal-role")
    client.post(
        "/api/workspace/members",
        json={"name": "Legal Reviewer", "email": legal_email, "password": PASSWORD, "role": "legal"},
    )
    with TestClient(app) as legal:
        assert legal.post("/api/auth/login", json={"email": legal_email, "password": PASSWORD}).status_code == 200
        ok = legal.post(f"/api/reviews/{review['id']}/override?justification=Approved by counsel, reference L-2026-14")
        assert ok.status_code == 200
        assert ok.json()["status"] == "ready_for_approval"
    activity = client.get("/api/workspace/activity").json()
    assert any(a["action"] == "review.overridden" for a in activity)


def test_review_runs_on_a_draft_policy_and_flags_legal_issues(client, admin_client):
    """A brand that has not published a policy must still be able to check content.

    Brand rules are provisional until approval; statutory legal guidelines are not.
    """
    signup_ok(client, account_type="creator", email=unique_email("draft"), name="Draft Policy Creator")
    brand = client.get("/api/brands").json()[0]
    assert brand["policy_status"] == "draft"

    content = client.post(
        "/api/content",
        json={
            "brand_id": brand["id"],
            "title": "draft policy check",
            "body_text": "Our cream cures eczema in 7 days. Guaranteed results.",
            "channel": "instagram_caption",
        },
    ).json()

    review = client.post("/api/reviews", json={"content_version_id": content["version_id"]})
    assert review.status_code == 201, review.text
    data = review.json()

    # the review says out loud that the policy is not enforced yet
    assert data["policy_state"]["status"] == "draft"
    assert data["policy_state"]["enforced"] is False
    assert data["policy_state"]["proposed_rules"] >= 1

    # and the legal registry still fires, with citations
    legal = [f for f in data["findings"] if f["guideline_code"]]
    assert legal, "legal guidelines must be checked even on a draft policy"
    dmr = next(f for f in legal if f["guideline_code"] == "IN-DMR-S3")
    assert dmr["severity"] == "critical"
    assert "Schedule I" in dmr["guideline_citation"]
    assert dmr["remediation"]
    assert data["hard_blocker"] is True
    assert data["routing"]["route"] == "legal"

    # approving the policy later does not require a re-check to be useful
    client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
    again = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
    assert again["policy_state"]["status"] == "published"
    assert again["policy_state"]["enforced"] is True


def test_accepting_a_fix_is_not_blocked_when_the_cta_is_only_a_button(admin_client):
    """A declared CTA that never appears in the body must not block every patch."""
    with TestClient(app) as client:
        signup_ok(client, account_type="creator", email=unique_email("cta"), name="CTA Tester")
        brand = client.get("/api/brands").json()[0]
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        content = client.post(
            "/api/content",
            json={
                "brand_id": brand["id"],
                "title": "Button CTA",
                "body_text": "Our oats cure acidity. Guaranteed results, lasts 30 days.",
                "channel": "instagram_caption",
                "desired_cta": "Shop now",   # rendered as a button, not in the copy
            },
        ).json()
        review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
        assert review["patches"]
        for patch in review["patches"]:
            decision = client.post(f"/api/rewrite-patches/{patch['id']}/decision", json={"decision": "accepted"}).json()
            assert decision["blocked"] is False, decision["drift"]
            cta = next(c for c in decision["drift"]["invariants"] if c["key"] == "cta_preserved")
            assert cta["passed"] is True
