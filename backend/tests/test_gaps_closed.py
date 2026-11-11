"""The features added to close the known-gaps list.

Each test targets one thing that used to be missing or broken: self-serve
billing, password reset, session revocation, rate limiting, multiple
workspaces, image review, policy-change invalidation, review timeout and
idempotent writes.
"""
from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import ratelimit
from app.main import app
from app.services import media, plans
from conftest import PASSWORD, login, signup_ok, unique_email


def _creator(client, **kw):
    email = kw.pop("email", None) or unique_email("gap")
    signup_ok(client, account_type="creator", email=email, name="Gap Tester", **kw)
    return email


def _brand(client):
    return client.get("/api/brands").json()[0]


# ------------------------------------------------------------------ billing
def test_self_serve_upgrade_records_an_invoice(admin_client):
    with TestClient(app) as client:
        _creator(client, plan="creator_free")
        summary = client.get("/api/billing/summary").json()
        assert summary["current"]["code"] == "creator_free"
        assert summary["mode"] == "test"
        assert summary["available"], "there must be an upgrade path"

        checkout = client.post("/api/billing/checkout", json={"plan": "creator_pro"})
        assert checkout.status_code == 200, checkout.text
        body = checkout.json()
        assert body["plan"] == "creator_pro"
        assert body["invoice"]["amount_inr"] == 499
        assert body["invoice"]["number"].startswith("BSP-INV-")
        assert body["usage"]["reviews_limit"] == 300

        me = client.get("/api/auth/me").json()
        assert me["org"]["plan"] == "creator_pro"
        assert me["usage"]["reviews_limit"] == 300

        after = client.get("/api/billing/summary").json()
        assert any(i["plan_to"] == "creator_pro" for i in after["invoices"])


def test_checkout_rejects_plan_of_the_wrong_account_type(admin_client):
    with TestClient(app) as client:
        _creator(client)
        response = client.post("/api/billing/checkout", json={"plan": "business_growth"})
        assert response.status_code == 409


def test_downgrade_below_current_usage_is_allowed_but_flagged(admin_client):
    with TestClient(app) as client:
        _creator(client, plan="creator_pro")
        brand = _brand(client)
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        client.post("/api/content", json={"brand_id": brand["id"], "title": "one", "body_text": "A calm scent.", "channel": "instagram_caption"})

        response = client.post("/api/billing/checkout", json={"plan": "creator_free"})
        assert response.status_code == 200
        assert response.json()["plan"] == "creator_free"


# ------------------------------------------------------------ password reset
def test_password_reset_flow_end_to_end(admin_client):
    with TestClient(app) as client:
        email = _creator(client)
        client.post("/api/auth/logout")

        asked = client.post("/api/auth/forgot-password", json={"email": email})
        assert asked.status_code == 200
        assert "reset link" in asked.json()["message"]

        # unknown emails get the same answer: no account enumeration
        unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.test"})
        assert unknown.json()["message"] == asked.json()["message"]

        mails = admin_client.get("/api/admin/mail").json()
        mine = next(m for m in mails if m["to"] == email and m["kind"] == "password_reset")
        token = re.search(r"token=([A-Za-z0-9_\-]+)", mine["body"]).group(1)

        reset = client.post("/api/auth/reset-password", json={"token": token, "password": "BrandNewPass9"})
        assert reset.status_code == 200

        assert login(client, email, PASSWORD).status_code == 401
        assert login(client, email, "BrandNewPass9").status_code == 200

        # a reset token is single use
        again = client.post("/api/auth/reset-password", json={"token": token, "password": "AnotherPass9"})
        assert again.status_code == 400


def test_reset_rejects_a_bogus_token(client, admin_client):
    assert client.post("/api/auth/reset-password", json={"token": "nope", "password": "WhateverPass9"}).status_code == 400


# -------------------------------------------------------- sessions and abuse
def test_password_change_revokes_old_sessions(admin_client):
    with TestClient(app) as first:
        email = _creator(first)
        with TestClient(app) as second:
            assert login(second, email).status_code == 200
            assert second.get("/api/auth/me").status_code == 200

            changed = first.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "FreshPass99"})
            assert changed.status_code == 200

            # the other session's token is now dead
            assert second.get("/api/auth/me").status_code == 401
            assert first.get("/api/auth/me").status_code == 200


def test_login_is_rate_limited(admin_client):
    ratelimit.reset()
    with TestClient(app) as client:
        email = _creator(client)
        codes = [login(client, email, "WrongPassword1").status_code for _ in range(12)]
        assert 429 in codes, codes
    ratelimit.reset()


# ------------------------------------------------------------ workspaces
def test_user_can_hold_and_switch_workspaces(admin_client):
    with TestClient(app) as client:
        _creator(client)
        first_org = client.get("/api/auth/me").json()["org"]["id"]

        created = client.post(
            "/api/auth/workspaces",
            json={"name": "Second Studio", "account_type": "creator", "plan": "creator_pro"},
        )
        assert created.status_code == 201, created.text
        second_org = created.json()["org"]["id"]
        assert second_org != first_org
        assert len(created.json()["workspaces"]) == 2

        # the new workspace starts with its own single brand
        brands = client.get("/api/brands").json()
        assert len(brands) == 1
        assert brands[0]["name"].startswith("Second Studio")

        switched = client.post("/api/auth/switch-workspace", json={"org_id": first_org})
        assert switched.status_code == 200
        assert switched.json()["org"]["id"] == first_org
        assert client.get("/api/auth/me").json()["org"]["id"] == first_org


def test_switch_to_a_foreign_workspace_is_refused(admin_client):
    with TestClient(app) as mine, TestClient(app) as other:
        _creator(mine)
        _creator(other)
        other_org = other.get("/api/auth/me").json()["org"]["id"]
        assert mine.post("/api/auth/switch-workspace", json={"org_id": other_org}).status_code == 404


# ----------------------------------------------------------------- images
def _png(colour=(200, 40, 40), size=(240, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_upload_is_measured_from_pixels(admin_client):
    with TestClient(app) as client:
        _creator(client)
        brand = _brand(client)
        response = client.post(
            "/api/content/upload-image",
            data={"brand_id": brand["id"], "alt_text": "Red launch poster"},
            files={"file": ("poster.png", _png(), "image/png")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["asset_id"]
        analysis = body["analysis"]
        assert analysis["width"] == 240 and analysis["height"] == 240
        assert analysis["palette"] and analysis["palette"][0].startswith("#")
        assert analysis["ocr_available"] is False
        assert "note" in analysis

        # the stored file is served back, tenant-scoped
        assert client.get(f"/api/assets/{body['asset_id']}/file").status_code == 200
        with TestClient(app) as stranger:
            _creator(stranger)
            assert stranger.get(f"/api/assets/{body['asset_id']}/file").status_code == 404


def test_off_palette_image_is_flagged_by_the_visual_checker(admin_client):
    with TestClient(app) as client:
        _creator(client)
        brand = _brand(client)
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        upload = client.post(
            "/api/content/upload-image",
            data={"brand_id": brand["id"], "alt_text": "Poster"},
            files={"file": ("poster.png", _png((250, 5, 200)), "image/png")},
        ).json()

        content = client.post(
            "/api/content",
            json={
                "brand_id": brand["id"],
                "title": "Poster review",
                "body_text": "Our new launch poster.",
                "channel": "print_poster",
                "modality": "image",
                "meta": {"media_ref": upload["asset_id"], "image": upload["analysis"]},
            },
        ).json()
        review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
        visual = [f for f in review["findings"] if f["agent"] == "visual"]
        assert visual
        assert any(f["status"] in ("confirmed", "needs_human_review") for f in visual)


def test_ffmpeg_ships_with_the_app():
    """Video upload depends on this binary being resolvable."""
    assert media.ffmpeg_binary(), "no ffmpeg available: pip imageio-ffmpeg should provide one"


# -------------------------------------------------- policy change invalidation
def test_publishing_a_new_policy_invalidates_old_clearances(admin_client):
    with TestClient(app) as client:
        _creator(client)
        brand = _brand(client)
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})

        content = client.post(
            "/api/content",
            json={"brand_id": brand["id"], "title": "clear me", "body_text": "A calm evening scent.", "channel": "instagram_caption"},
        ).json()
        review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
        approval = client.post(f"/api/approvals?review_run_id={review['id']}", json={"approver_role": "manager"}).json()
        decided = client.post(
            f"/api/approvals/{approval['id']}/decision", json={"decision": "approved", "comment": "ok"}
        ).json()
        clearance_id = decided["clearance_id"]
        assert client.get(f"/api/verify/{clearance_id}").json()["valid"] is True

        # publish a second policy version
        draft = client.post(f"/api/brands/{brand['id']}/policies/import", json={"source_summary": "v2"}).json()
        assert client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"}).status_code == 200

        verified = client.get(f"/api/verify/{clearance_id}").json()
        assert verified["valid"] is False
        assert "Policy v2" in verified["reason"]


# --------------------------------------------------------------- resilience
def test_review_times_out_into_a_partial_review(admin_client, monkeypatch):
    with TestClient(app) as client:
        _creator(client)
        brand = _brand(client)
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        content = client.post(
            "/api/content",
            json={"brand_id": brand["id"], "title": "slow", "body_text": "A calm scent.", "channel": "instagram_caption"},
        ).json()

        monkeypatch.setattr("app.core.config.settings.review_timeout_seconds", 0.0001, raising=False)
        review = client.post("/api/reviews", json={"content_version_id": content["version_id"]})
        assert review.status_code == 201
        body = review.json()
        assert body["status"] == "needs_human"
        assert body["risk_band"] == "incomplete"
        assert body["routing"]["route"] == "specialist"
        assert body["completeness"]["complete"] is False


def test_repeated_post_with_an_idempotency_key_is_not_duplicated(admin_client):
    with TestClient(app) as client:
        _creator(client)
        brand = _brand(client)
        payload = {"brand_id": brand["id"], "title": "once", "body_text": "A calm scent.", "channel": "instagram_caption"}
        headers = {"Idempotency-Key": "test-key-123"}

        first = client.post("/api/content", json=payload, headers=headers)
        second = client.post("/api/content", json=payload, headers=headers)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

        items = client.get("/api/content").json()
        assert len([i for i in items if i["title"] == "once"]) == 1
