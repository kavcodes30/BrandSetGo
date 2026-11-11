"""Accounts, sessions and the creator/business split."""
from __future__ import annotations

from conftest import PASSWORD, login, signup, signup_ok, unique_email


def test_signup_requires_no_existing_account(client, admin_client):
    email = unique_email("creator")
    data = signup_ok(client, account_type="creator", name="Meera Iyer", email=email, plan="creator_pro")

    assert data["user"]["email"] == email
    assert data["user"]["account_type"] == "creator"
    assert data["org"]["account_type"] == "creator"
    assert data["org"]["plan"] == "creator_pro"
    assert data["role"] == "owner"
    assert data["platform_admin"] is False

    # a creator workspace is born with one personal brand and a draft policy
    brands = client.get("/api/brands").json()
    assert len(brands) == 1
    assert brands[0]["is_personal"] is True or brands[0]["kind"] == "personal"
    assert brands[0]["policy_status"] in ("draft", "published")


def test_signup_business_needs_company_name(client, admin_client):
    response = signup(client, account_type="business", name="No Company", company="")
    assert response.status_code == 400
    assert "company name" in response.json()["detail"].lower()


def test_duplicate_email_is_rejected(client, admin_client):
    email = unique_email("dupe")
    signup_ok(client, account_type="creator", email=email)
    again = signup(client, account_type="creator", email=email)
    assert again.status_code == 409


def test_weak_password_is_rejected(client, admin_client):
    response = signup(client, account_type="creator", password="short")
    assert response.status_code == 400
    assert "8 characters" in response.json()["detail"]


def test_password_needs_more_than_letters(client, admin_client):
    response = signup(client, account_type="creator", password="onlylettershere")
    assert response.status_code == 400


def test_login_and_logout(client, admin_client):
    email = unique_email("login")
    signup_ok(client, account_type="creator", email=email)

    fresh = client
    fresh.post("/api/auth/logout")
    assert fresh.get("/api/auth/me").status_code == 401

    wrong = login(client, email, "WrongPassword1")
    assert wrong.status_code == 401

    ok = login(client, email)
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == email
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_session_cookie_is_httponly(client, admin_client):
    email = unique_email("cookie")
    signup_ok(client, account_type="creator", email=email)
    response = login(client, email)
    cookie = response.headers.get("set-cookie", "")
    assert "bs_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "samesite=lax" in cookie.lower()


def test_me_requires_a_session(fresh):
    assert fresh.get("/api/auth/me").status_code == 401
    assert fresh.get("/api/brands").status_code == 401
    assert fresh.get("/api/dashboard").status_code == 401


def test_password_change(client, admin_client):
    email = unique_email("pw")
    signup_ok(client, account_type="creator", email=email)

    bad = client.post("/api/auth/password", json={"current_password": "nope1234", "new_password": "NewSecret9"})
    assert bad.status_code == 401

    good = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "NewSecret9"})
    assert good.status_code == 200

    client.post("/api/auth/logout")
    assert login(client, email, "NewSecret9").status_code == 200


def test_first_user_is_platform_admin(admin_client):
    me = admin_client.get("/api/auth/me").json()
    assert me["platform_admin"] is True
    assert me["user"]["platform_role"] == "admin"


def test_plans_endpoint_is_public_and_typed(fresh):
    response = fresh.get("/api/auth/plans?account_type=creator")
    assert response.status_code == 200
    plans = response.json()
    assert plans and all(p["account_type"] == "creator" for p in plans)
    assert any(p["price_inr"] == 0 for p in plans)
