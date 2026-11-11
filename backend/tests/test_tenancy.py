"""Workspaces are isolated, and the admin surface is gated."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from conftest import signup_ok, unique_email


def test_brands_are_scoped_to_the_workspace(admin_client):
    with TestClient(app) as first, TestClient(app) as second:
        a = signup_ok(first, account_type="creator", email=unique_email("a"))
        b = signup_ok(second, account_type="creator", email=unique_email("b"))

        a_brand = first.get("/api/brands").json()[0]
        b_brand = second.get("/api/brands").json()[0]
        assert a_brand["id"] != b_brand["id"]

        # B cannot read A's brand or content by id
        assert second.get(f"/api/brands/{a_brand['id']}").status_code == 404
        assert second.post(
            "/api/content",
            json={"brand_id": a_brand["id"], "title": "sneaky", "body_text": "hello", "channel": "instagram_caption"},
        ).status_code == 404


def test_creator_cannot_open_business_dashboard(admin_client):
    with TestClient(app) as creator:
        signup_ok(creator, account_type="creator", email=unique_email("creator"))
        assert creator.get("/api/workspace/business").status_code == 403
        assert creator.get("/api/workspace/creator").status_code == 200


def test_business_cannot_open_creator_dashboard(admin_client):
    with TestClient(app) as business:
        signup_ok(business, account_type="business", email=unique_email("biz"), company="Acme Foods")
        assert business.get("/api/workspace/creator").status_code == 403
        assert business.get("/api/workspace/business").status_code == 200


def test_admin_surface_is_platform_admin_only(admin_client):
    assert admin_client.get("/api/admin/overview").status_code == 200

    with TestClient(app) as normal:
        signup_ok(normal, account_type="business", email=unique_email("notadmin"), company="Ordinary Co")
        assert normal.get("/api/admin/overview").status_code == 403
        assert normal.get("/api/admin/users").status_code == 403
        assert normal.patch("/api/admin/orgs/x/plan", json={"plan": "enterprise"}).status_code == 403


def test_reviews_are_scoped(admin_client):
    with TestClient(app) as first, TestClient(app) as second:
        signup_ok(first, account_type="creator", email=unique_email("r1"))
        signup_ok(second, account_type="creator", email=unique_email("r2"))
        brand = first.get("/api/brands").json()[0]
        first.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        content = first.post(
            "/api/content",
            json={"brand_id": brand["id"], "title": "hello", "body_text": "A calm evening scent.", "channel": "instagram_caption"},
        ).json()
        review = first.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
        assert second.get(f"/api/reviews/{review['id']}").status_code == 404
