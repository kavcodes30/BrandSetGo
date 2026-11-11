"""The operator surface behind the pricing model."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from conftest import PASSWORD, login, signup_ok, unique_email


def test_overview_reports_accounts_plans_and_revenue(admin_client):
    data = admin_client.get("/api/admin/overview").json()
    assert data["totals"]["users"] >= 1
    assert data["totals"]["orgs"] >= 1
    assert "mrr_inr" in data["revenue"] and "arr_inr" in data["revenue"]
    assert data["plans"] and all("price_inr" in p for p in data["plans"])
    assert len(data["signups_by_week"]) == 8
    assert data["recent_users"]


def test_users_list_carries_plan_and_value(admin_client):
    with TestClient(app) as business:
        email = unique_email("paid")
        signup_ok(business, account_type="business", name="Paid Co", email=email, company="Paid Co", plan="business_growth")

    rows = admin_client.get("/api/admin/users").json()
    row = next(r for r in rows if r["email"] == email)
    assert row["plan"] == "business_growth"
    assert row["mrr_inr"] == 7999
    assert row["account_type"] == "business"
    assert row["org_name"] == "Paid Co"

    filtered = admin_client.get("/api/admin/users?query=paid").json()
    assert any(r["email"] == email for r in filtered)


def test_plan_change_updates_seats_and_rejects_wrong_type(admin_client):
    with TestClient(app) as business:
        email = unique_email("upgrade")
        signup_ok(business, account_type="business", email=email, company="Upgrade Co", plan="business_starter")
        org_id = business.get("/api/auth/me").json()["org"]["id"]

    changed = admin_client.patch(f"/api/admin/orgs/{org_id}/plan", json={"plan": "business_growth"})
    assert changed.status_code == 200
    assert changed.json()["plan"] == "business_growth"
    assert changed.json()["seats"] == 20

    mismatch = admin_client.patch(f"/api/admin/orgs/{org_id}/plan", json={"plan": "creator_pro"})
    assert mismatch.status_code == 400

    orgs = admin_client.get("/api/admin/orgs").json()
    row = next(o for o in orgs if o["id"] == org_id)
    assert row["mrr_inr"] == 7999


def test_suspending_a_user_blocks_login(admin_client):
    with TestClient(app) as business:
        email = unique_email("suspend")
        signup_ok(business, account_type="business", email=email, company="Suspend Co")

    user_id = next(u for u in admin_client.get("/api/admin/users").json() if u["email"] == email)["id"]
    assert admin_client.patch(f"/api/admin/users/{user_id}", json={"status": "suspended"}).status_code == 200

    with TestClient(app) as blocked:
        response = login(blocked, email, PASSWORD)
        assert response.status_code == 403
        assert "suspended" in response.json()["detail"].lower()

    admin_client.patch(f"/api/admin/users/{user_id}", json={"status": "active"})


def test_admin_cannot_suspend_themselves(admin_client):
    me = admin_client.get("/api/auth/me").json()["user"]["id"]
    response = admin_client.patch(f"/api/admin/users/{me}", json={"status": "suspended"})
    assert response.status_code == 400
