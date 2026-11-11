"""Test fixtures: a throwaway database, no demo data, no network.

Every test signs up its own accounts through the real API, so the suite proves
the same paths a user takes.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["SARVAM_API_KEY"] = ""
# a bundled key file must never leak into the test run
os.environ["SARVAM_KEY_FILE"] = "/nonexistent/test-sarvam.key"
os.environ["FIRST_USER_IS_ADMIN"] = "true"
os.environ["SECRET_KEY"] = "test-secret-do-not-use-outside-tests"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = "CorrectHorse9"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.test"


def signup(
    client: TestClient,
    *,
    account_type: str = "creator",
    name: str = "Test User",
    email: str | None = None,
    password: str = PASSWORD,
    company: str | None = None,
    plan: str | None = None,
):
    payload = {
        "name": name,
        "email": email or unique_email(account_type),
        "password": password,
        "account_type": account_type,
    }
    if company:
        payload["company"] = company
    if plan:
        payload["plan"] = plan
    return client.post("/api/auth/signup", json=payload)


def signup_ok(client: TestClient, **kwargs) -> dict:
    response = signup(client, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fresh():
    """A client with its own cookie jar, for multi-user scenarios."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_client():
    """The first account on a fresh install becomes the platform admin."""
    with TestClient(app) as test_client:
        payload = signup_ok(
            test_client,
            account_type="business",
            name="Platform Admin",
            email="platform-admin@example.test",
            company="BrandSetGo Ops",
            plan="enterprise",
        )
        assert payload["platform_admin"] is True
        yield test_client
