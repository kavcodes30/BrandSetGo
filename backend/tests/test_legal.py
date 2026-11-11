"""The legal registry, the deterministic scan, and the model's guard rails."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.legal import guidelines as G
from app.legal import ai as legal_ai
from app.main import app
from app.services import sarvam
from conftest import signup_ok, unique_email


def _creator(client):
    signup_ok(client, account_type="creator", email=unique_email("legal"))


def test_registry_has_citations_for_every_guideline(client, admin_client):
    _creator(client)
    data = client.get("/api/legal/guidelines").json()
    assert data["registry_version"] == G.REGISTRY_VERSION
    assert "not legal advice" in data["disclaimer"].lower()
    assert len(data["guidelines"]) >= 20
    for item in data["guidelines"]:
        assert item["code"] and item["title"] and item["authority"] and item["citation"]
        assert item["obligation"] and item["remediation"]
        assert item["severity"] in ("low", "medium", "high", "critical")


def test_single_guideline_lookup(client, admin_client):
    _creator(client)
    one = client.get("/api/legal/guidelines/IN-DMR-S3").json()
    assert "Drugs and Magic Remedies" in one["authority"]
    assert "Schedule I" in one["citation"]
    assert client.get("/api/legal/guidelines/NOPE").status_code == 404


def test_preview_flags_a_disease_cure_claim(client, admin_client):
    _creator(client)
    data = client.post(
        "/api/legal/preview",
        json={"text": "Our syrup cures diabetes in 30 days.", "sector": "health", "channel": "instagram_caption"},
    ).json()
    codes = {f["guideline_code"] for f in data["findings"]}
    assert "IN-DMR-S3" in codes
    finding = next(f for f in data["findings"] if f["guideline_code"] == "IN-DMR-S3")
    assert finding["severity"] == "critical"
    assert "Schedule I" in finding["guideline_citation"]
    assert finding["remediation"]
    assert finding["legal_basis"]


def test_preview_requires_influencer_disclosure(client, admin_client):
    _creator(client)
    data = client.post(
        "/api/legal/preview",
        json={"text": "Gifted by Glow Co, this serum is lovely.", "sector": "beauty", "channel": "instagram_caption"},
    ).json()
    assert any(f["guideline_code"] == "IN-ASCI-INFLUENCER-2021" for f in data["findings"])

    disclosed = client.post(
        "/api/legal/preview",
        json={"text": "#ad Gifted by Glow Co, this serum is lovely.", "sector": "beauty", "channel": "instagram_caption"},
    ).json()
    assert not any(f["guideline_code"] == "IN-ASCI-INFLUENCER-2021" for f in disclosed["findings"])


def test_disclaimer_rule_does_not_fire_on_a_prohibited_cure_claim(client, admin_client):
    _creator(client)
    data = client.post(
        "/api/legal/preview",
        json={"text": "This cream cures eczema.", "sector": "skincare", "channel": "product_page"},
    ).json()
    codes = {f["guideline_code"] for f in data["findings"]}
    assert "IN-DMR-S3" in codes
    # a cure claim is prohibited outright; it is not a missing-disclaimer problem
    assert "IN-CCPA-DISCLAIMER-2022" not in codes


def test_price_without_package_declaration(client, admin_client):
    _creator(client)
    data = client.post(
        "/api/legal/preview",
        json={"text": "Buy the 50 ml bottle at ₹899 today.", "sector": "skincare", "channel": "product_page"},
    ).json()
    assert any(f["guideline_code"] == "IN-LM-PACKAGED-2011" for f in data["findings"])

    declared = client.post(
        "/api/legal/preview",
        json={"text": "Buy the 50 ml bottle at ₹899, MRP inclusive of all taxes.", "sector": "skincare", "channel": "product_page"},
    ).json()
    assert not any(f["guideline_code"] == "IN-LM-PACKAGED-2011" for f in declared["findings"])


@pytest.mark.asyncio
async def test_ai_legal_rejects_a_guideline_not_in_scope(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.sarvam_api_key", "test-key", raising=False)
    monkeypatch.setattr("app.core.config.settings.ai_legal_review", True, raising=False)
    sarvam.reset_state()

    async def fake(system, user, **kw):
        return sarvam.SarvamResult(
            ok=True,
            data={"findings": [{"guideline_code": "IN-MADE-UP", "span": "cures", "severity": "high",
                                "confidence": 0.9, "why": "x", "fix": "y"}]},
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    findings, meta = await legal_ai.scan(
        "This cream cures eczema.", sector="skincare", channel="product_page", language="en", already_reported=[]
    )
    assert findings == []
    assert meta["rejected"] == 1
    assert any("not in scope" in r for r in meta["reasons"])


@pytest.mark.asyncio
async def test_ai_legal_cannot_quote_text_outside_the_copy(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.sarvam_api_key", "test-key", raising=False)
    sarvam.reset_state()

    async def fake(system, user, **kw):
        return sarvam.SarvamResult(
            ok=True,
            data={"findings": [{"guideline_code": "IN-DMR-S3", "span": "cures cancer", "severity": "high",
                                "confidence": 0.9, "why": "x", "fix": "y"}]},
            usage={},
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    findings, meta = await legal_ai.scan(
        "This cream cures eczema.", sector="skincare", channel="product_page", language="en", already_reported=[]
    )
    assert findings == []
    assert any("substring" in r for r in meta["reasons"])


@pytest.mark.asyncio
async def test_ai_legal_never_issues_critical(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.sarvam_api_key", "test-key", raising=False)
    sarvam.reset_state()

    async def fake(system, user, **kw):
        return sarvam.SarvamResult(
            ok=True,
            data={"findings": [{"guideline_code": "IN-ASCI-I4-DURATION", "span": "lasts 24 hours",
                                "severity": "critical", "confidence": 0.9, "why": "x", "fix": "y"}]},
            usage={},
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    findings, _ = await legal_ai.scan(
        "It lasts 24 hours.", sector="perfume", channel="instagram_caption", language="en", already_reported=[]
    )
    assert findings and findings[0].severity == "high"
