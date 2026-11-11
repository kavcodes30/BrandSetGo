"""Classification runs at ingest, is stored, and is reused by the review.

Also covers how a deployment supplies the Sarvam key: env var, or a mounted key
file, with no code change.
"""
from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import sarvam
from conftest import signup_ok, unique_email


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ai_classification", True, raising=False)
    monkeypatch.setattr(settings, "ai_semantic_review", True, raising=False)
    monkeypatch.setattr(settings, "ai_legal_review", True, raising=False)
    monkeypatch.setattr(settings, "ai_rewrite", True, raising=False)
    sarvam.reset_state()
    yield
    sarvam.reset_state()


def _classification_payload():
    return {
        "language": "en",
        "content_type": "ad",
        "category": "skincare",
        "audience": "adults",
        "sensitivity": "internal",
        "pii": ["none"],
        "claims": [{"text": "lasts 24 hours", "type": "duration", "verifiable": True}],
        "risk_hints": ["unsubstantiated duration"],
        "confidence": 0.91,
    }


def test_classification_is_stored_at_ingest_and_reused_by_the_review(ai_on, monkeypatch, admin_client):
    # a separate client: signing up must not replace the admin fixture's session
    calls = {"classification": 0, "other": 0}

    async def fake(system, user, **kw):
        if "content_type" in user and "Schema:" in user:
            calls["classification"] += 1
        else:
            calls["other"] += 1
        if "content_type" in user and "Schema:" in user:
            data = _classification_payload()
        elif "GUIDELINES IN SCOPE" in user:
            data = {"findings": [], "overall": "compliant"}
        else:
            data = {"findings": [], "overall": "nothing new"}
        return sarvam.SarvamResult(ok=True, data=data, text="", usage={"prompt_tokens": 10, "completion_tokens": 5}, latency_ms=8)

    monkeypatch.setattr(sarvam, "chat_json", fake)

    with TestClient(app) as client:
        return _ingest_flow(client, calls)


def _ingest_flow(client, calls):
    signup_ok(client, account_type="creator", email=unique_email("ingest"), name="Ingest Tester")
    brand = client.get("/api/brands").json()[0]
    client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})

    created = client.post(
        "/api/content",
        json={
            "brand_id": brand["id"],
            "title": "Ingest classification",
            "body_text": "Noir Oud lasts 24 hours. Shop the collection.",
            "channel": "instagram_caption",
            "desired_cta": "Shop the collection",
            "meta": {"contrast_ratio": 5.2},
        },
    ).json()

    # the classification already exists before any review is run
    assert calls["classification"] == 1, "classification must run once, at ingest"
    assert created["classification"]["source"] == "sarvam"
    assert created["classification"]["category"] == "skincare"
    assert created["classification"]["claims"] == 1

    review = client.post("/api/reviews", json={"content_version_id": created["version_id"]}).json()
    assert calls["classification"] == 1, "the review must reuse the stored classification"
    assert review["classification"]["source"] == "sarvam"

    # explicit re-run is available and refreshes the stored value
    again = client.post(f"/api/content/{created['id']}/classify")
    assert again.status_code == 200
    assert calls["classification"] == 2


def test_a_key_file_is_enough_to_enable_live_models(tmp_path, monkeypatch):
    key_file = tmp_path / "sarvam.key"
    key_file.write_text("file-supplied-key\n")
    monkeypatch.setattr(settings, "sarvam_api_key", "", raising=False)
    monkeypatch.setattr(settings, "sarvam_key_file", str(key_file), raising=False)

    assert settings.api_key == "file-supplied-key"
    assert sarvam.enabled() is True


def test_without_a_key_the_platform_reports_deterministic_mode(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "", raising=False)
    monkeypatch.setattr(settings, "sarvam_key_file", "/nonexistent/key.file", raising=False)
    assert settings.api_key == ""
    assert sarvam.enabled() is False
