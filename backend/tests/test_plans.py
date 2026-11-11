"""Plan limits: brands, seats and the monthly review quota."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import plans
from conftest import signup_ok, unique_email


def test_creator_free_allows_one_brand(admin_client):
    with TestClient(app) as creator:
        signup_ok(creator, account_type="creator", email=unique_email("free"), plan="creator_free")
        assert len(creator.get("/api/brands").json()) == 1
        second = creator.post("/api/brands", json={"name": "Second Brand", "kind": "personal"})
        assert second.status_code == 402
        assert "brand" in second.json()["detail"].lower()


def test_creator_cannot_add_team_members(admin_client):
    with TestClient(app) as creator:
        signup_ok(creator, account_type="creator", email=unique_email("solo"))
        response = creator.post(
            "/api/workspace/members",
            json={"name": "Someone", "email": unique_email("mate"), "password": "CorrectHorse9", "role": "creator"},
        )
        assert response.status_code == 400
        assert "single-seat" in response.json()["detail"].lower()


def test_business_seat_limit_is_enforced(admin_client):
    with TestClient(app) as business:
        signup_ok(business, account_type="business", email=unique_email("seats"), company="Seat Co", plan="business_starter")
        # starter includes 5 seats; the owner is seat 1
        for i in range(4):
            response = business.post(
                "/api/workspace/members",
                json={"name": f"Member {i}", "email": unique_email(f"m{i}"), "password": "CorrectHorse9", "role": "creator"},
            )
            assert response.status_code == 201, response.text
        overflow = business.post(
            "/api/workspace/members",
            json={"name": "One Too Many", "email": unique_email("over"), "password": "CorrectHorse9", "role": "creator"},
        )
        assert overflow.status_code == 402
        assert "seat" in overflow.json()["detail"].lower()


def test_review_quota_blocks_and_explains(admin_client, monkeypatch):
    with TestClient(app) as creator:
        signup_ok(creator, account_type="creator", email=unique_email("quota"), plan="creator_free")
        brand = creator.get("/api/brands").json()[0]
        creator.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        content = creator.post(
            "/api/content",
            json={"brand_id": brand["id"], "title": "first", "body_text": "A calm evening scent.", "channel": "instagram_caption"},
        ).json()

        # a free plan with zero included reviews models an exhausted quota
        monkeypatch.setitem(plans.PLANS["creator_free"], "reviews_per_month", 0)
        blocked = creator.post("/api/reviews", json={"content_version_id": content["version_id"]})
        assert blocked.status_code == 402
        assert "Upgrade" in blocked.json()["detail"]

        monkeypatch.setitem(plans.PLANS["creator_free"], "reviews_per_month", 20)
        allowed = creator.post("/api/reviews", json={"content_version_id": content["version_id"]})
        assert allowed.status_code == 201
