"""The Sarvam layer is only trustworthy if its guards hold.

These tests mock the gateway: no network, no key, fully deterministic.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import ApprovedClaim, BrandRule
from app.services import ai_review, classify, sarvam
from app.services.ai_review import AIFinding, clamp_severity, verify_ai_finding
from conftest import signup_ok, unique_email


def fake_result(data: dict, latency_ms: int = 12) -> sarvam.SarvamResult:
    return sarvam.SarvamResult(
        ok=True,
        data=data,
        text="",
        usage={"prompt_tokens": 100, "completion_tokens": 40},
        latency_ms=latency_ms,
    )


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ai_classification", True, raising=False)
    monkeypatch.setattr(settings, "ai_semantic_review", True, raising=False)
    monkeypatch.setattr(settings, "ai_rewrite", True, raising=False)
    monkeypatch.setattr(settings, "ai_legal_review", True, raising=False)
    sarvam.reset_state()
    yield
    sarvam.reset_state()


def _rule(code="R-01", category="claims", severity="high") -> BrandRule:
    return BrandRule(
        id=code,
        policy_version_id="p",
        code=code,
        title="No unsubstantiated performance claims" if category == "claims" else "Brand voice",
        category=category,
        statement="Claims must cite an approved claim record.",
        severity=severity,
        scope=[],
        source_ref="",
        evidence_ref="Approved claims registry",
        is_authoritative=True,
    )


def test_json_extraction_handles_fences_and_prose():
    assert sarvam.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert sarvam.extract_json('Sure! {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    assert sarvam.extract_json("no json here") is None


async def test_classification_drops_hallucinated_claims(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return fake_result(
            {
                "language": "en",
                "content_type": "ad",
                "category": "perfume",
                "audience": "buyers",
                "sensitivity": "public",
                "pii": ["none"],
                "claims": [
                    {"text": "lasts 24 hours", "type": "duration", "verifiable": True},
                    {"text": "dermatologist approved by AIIMS", "type": "clinical", "verifiable": True},
                ],
                "confidence": 0.9,
            }
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    out = await classify.classify("Noir Oud lasts 24 hours.", declared_sensitivity="internal")
    assert [c.text for c in out.claims] == ["lasts 24 hours"]
    assert out.dropped_claims == 1
    assert out.source == "sarvam"


async def test_classification_corrects_language_from_script(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return fake_result(
            {
                "language": "en",
                "content_type": "ad",
                "category": "perfume",
                "sensitivity": "public",
                "pii": ["none"],
                "claims": [],
                "confidence": 0.8,
            }
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    out = await classify.classify("नोअर ओउद सुगंध", declared_language="mr", brand_languages=["en", "mr"])
    assert out.language == "mr"


async def test_sensitivity_can_only_be_raised(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return fake_result(
            {
                "language": "en",
                "content_type": "email",
                "category": "other",
                "sensitivity": "public",
                "pii": ["none"],
                "claims": [],
                "confidence": 0.8,
            }
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    out = await classify.classify(
        "Write to priya@example.com about the launch.", declared_sensitivity="confidential"
    )
    assert out.sensitivity == "confidential"
    assert "email" in out.pii


async def test_model_outage_falls_back_to_deterministic(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return sarvam.SarvamResult(ok=False, error="HTTP 503")

    monkeypatch.setattr(sarvam, "chat_json", fake)
    out = await classify.classify("Noir Oud lasts 24 hours.", declared_sensitivity="internal")
    assert out.source == "deterministic"
    assert any("deterministic fallback" in n for n in out.notes)


def test_ai_cannot_accuse_an_approved_claim():
    finding = AIFinding(
        agent="claims", rule_code="R-01", span="Helps skin look smoother",
        severity="high", confidence=0.9, status="confirmed", explanation="x",
    )
    claim = ApprovedClaim(
        brand_id="b",
        text="Helps skin look smoother with daily use",
        evidence_ref="CD-112",
        status="verified",
    )
    reason = verify_ai_finding(
        finding, rule=_rule(), content="Helps skin look smoother", language="en", claims=[claim], glossary=[]
    )
    assert reason and "approved claim" in reason


def test_ai_findings_are_limited_to_semantic_agents():
    facts = AIFinding(agent="facts", rule_code="R-02", span="30 ml", status="confirmed", confidence=0.9)
    rule = _rule(code="R-02", category="facts", severity="medium")
    assert verify_ai_finding(facts, rule=rule, content="30 ml", language="en", claims=[], glossary=[])


def test_ai_cannot_claim_critical_severity():
    assert clamp_severity("critical", "high", "claims") == "high"
    assert clamp_severity("low", "high", "claims") == "high"
    assert clamp_severity("high", "medium", "tone") == "medium"


def test_claims_finding_needs_promise_language_or_classification():
    finding = AIFinding(
        agent="claims", rule_code="R-01", span="20% off all gift boxes",
        severity="high", confidence=0.9, status="confirmed",
    )
    reason = verify_ai_finding(
        finding, rule=_rule(), content="20% off all gift boxes", language="en", claims=[], glossary=[]
    )
    assert reason and "no promise language" in reason

    bridged = verify_ai_finding(
        finding,
        rule=_rule(),
        content="20% off all gift boxes",
        language="en",
        claims=[],
        glossary=[],
        classified_claims=[{"text": "20% off all gift boxes", "type": "efficacy"}],
    )
    assert bridged is None


async def test_unknown_rule_is_rejected(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return fake_result(
            {
                "findings": [
                    {
                        "agent": "claims",
                        "rule_code": "R-99",
                        "span": "lasts 24 hours",
                        "title": "Made up rule",
                        "severity": "high",
                        "confidence": 0.9,
                        "status": "confirmed",
                        "explanation": "x",
                    }
                ]
            }
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)
    findings, meta = await ai_review.semantic_findings(
        content="lasts 24 hours",
        language="en",
        channel="instagram_caption",
        audience="",
        rules=[_rule()],
        claims=[],
        glossary=[],
        already_reported=[],
    )
    assert findings == []
    assert meta["rejected"] == 1
    assert any("not in force" in r for r in meta["reasons"])


async def test_ai_rewrite_guard_blocks_new_numbers(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        return fake_result({"replacement": "lasts 72 hours"})

    monkeypatch.setattr(sarvam, "chat_json", fake)
    replacement, meta = await ai_review.suggest_rewrite(
        span="lasts 24 hours", content="Noir Oud lasts 24 hours.", rule=_rule(), language="en"
    )
    assert replacement is None
    assert meta["error"] == "rejected-by-guard"


def test_review_merges_ai_findings_and_records_provenance(ai_on, monkeypatch):
    async def fake(system, user, **kw):
        if "content_type" in user and "Schema:" in user:
            return fake_result(
                {
                    "language": "en",
                    "content_type": "ad",
                    "category": "skincare",
                    "audience": "adults",
                    "sensitivity": "internal",
                    "pii": ["none"],
                    "claims": [{"text": "in a week", "type": "duration", "verifiable": True}],
                    "confidence": 0.9,
                }
            )
        if "GUIDELINES IN SCOPE" in user:
            return fake_result({"findings": [], "overall": "compliant"})
        return fake_result(
            {
                "findings": [
                    {
                        "agent": "claims",
                        "rule_code": "R-01",
                        "span": "in a week",
                        "title": "Implied timeframe promise",
                        "severity": "high",
                        "confidence": 0.8,
                        "status": "confirmed",
                        "explanation": "A result promised in a week needs substantiation.",
                    }
                ],
                "overall": "one implied promise",
            }
        )

    monkeypatch.setattr(sarvam, "chat_json", fake)

    with TestClient(app) as client:
        signup_ok(client, account_type="creator", email=unique_email("aimerge"), name="AI Merge")
        brand = client.get("/api/brands").json()[0]
        client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})
        content = client.post(
            "/api/content",
            json={
                "brand_id": brand["id"],
                "title": "AI merge check",
                "body_text": "Your skin will thank you in a week. Shop the launch.",
                "channel": "instagram_caption",
                "desired_cta": "Shop the launch",
                "meta": {"contrast_ratio": 5.2},
            },
        ).json()
        review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()

        ai_findings = [f for f in review["findings"] if f["source"] == "sarvam"]
        assert ai_findings, "the semantic reviewer finding must be persisted"
        assert ai_findings[0]["rule_code"] == "R-01"
        assert review["classification"]["source"] == "sarvam"
        assert review["ai_meta"]["calls"] >= 1
        assert review["ai_meta"]["tokens_in"] > 0
        assert review["status"] in ("needs_changes", "needs_human")


def test_ai_status_endpoint_reports_configuration(ai_on, admin_client):
    data = admin_client.get("/api/ai/status").json()
    assert data["enabled"] is True
    assert data["model"]
    assert "layers" in data
