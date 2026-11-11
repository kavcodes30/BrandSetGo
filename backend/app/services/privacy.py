"""Privacy Center: sensitivity labels, redaction preview, AI disclosure log.

Redaction must not erase facts the review needs. When it would, the service
says so and offers local-only processing or a human-only review instead of
silently sending the document out.
"""
from __future__ import annotations

import hashlib
import re

from app.core.config import settings
from app.models import Product
from app.services import sarvam

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")

SENSITIVITY_ORDER = ["public", "internal", "confidential", "restricted"]

POLICY_BY_SENSITIVITY = {
    "public": {"processors": ["Sarvam AI (hosted)"], "retention": "30 days", "external_ok": True, "redact": False},
    "internal": {"processors": ["Sarvam AI (hosted)"], "retention": "30 days", "external_ok": True, "redact": True},
    "confidential": {"processors": ["Sarvam AI (hosted, no-retention)"], "retention": "0 days", "external_ok": True, "redact": True},
    "restricted": {"processors": ["Self-hosted adapter"], "retention": "0 days", "external_ok": False, "redact": True},
}


def classify(text: str, declared: str, confidential_products: list[Product]) -> dict:
    """Raise the declared label if the text contains personal or secret data."""
    found: list[dict] = []
    for label, pattern in (("email", EMAIL), ("phone", PHONE), ("card", CARD), ("aadhaar", AADHAAR)):
        for m in pattern.finditer(text):
            found.append({"category": label, "value": m.group(0), "start": m.start(), "end": m.end()})
    for p in confidential_products:
        idx = text.lower().find(p.name.lower())
        if idx >= 0:
            found.append(
                {"category": "confidential_product", "value": p.name, "start": idx, "end": idx + len(p.name)}
            )

    effective = declared
    if found and SENSITIVITY_ORDER.index(declared) < SENSITIVITY_ORDER.index("confidential"):
        effective = "confidential"
    return {"declared": declared, "effective": effective, "detections": found, "policy": POLICY_BY_SENSITIVITY[effective]}


def redact(text: str, detections: list[dict]) -> tuple[str, list[dict]]:
    """Replace each detection with a stable, per-category token."""
    counters: dict[str, int] = {}
    tokens: dict[int, str] = {}
    for d in sorted(detections, key=lambda x: x["start"]):
        counters[d["category"]] = counters.get(d["category"], 0) + 1
        tokens[d["start"]] = f"[{d['category'].upper()}_{counters[d['category']]}]"

    out = text
    redaction_map: list[dict] = []
    for d in sorted(detections, key=lambda x: x["start"], reverse=True):
        token = tokens[d["start"]]
        out = out[: d["start"]] + token + out[d["end"] :]
        redaction_map.append({"token": token, "category": d["category"]})
    redaction_map.reverse()
    version = redaction_version(out)
    for entry in redaction_map:
        entry["redaction_version"] = version
    return out, redaction_map


def redaction_version(text: str) -> str:
    return "rv-" + hashlib.sha256(text.encode()).hexdigest()[:8]


def needs_local_processing(classification: dict, detections: list[dict]) -> bool:
    """Redaction that removes a required fact is worse than no redaction."""
    factual = [d for d in detections if d["category"] == "confidential_product"]
    return bool(factual) and classification["effective"] == "restricted"


def disclosure_payload(run_id: str, org_id: str, classification: dict, categories: list[str], tokens_in: int, tokens_out: int) -> dict:
    policy = classification["policy"]
    return {
        "org_id": org_id,
        "review_run_id": run_id,
        "processor": policy["processors"][0],
        "model": sarvam.model_name(),
        "region": settings.sarvam_region if sarvam.enabled() else "local (no transfer)",
        "sensitivity": classification["effective"],
        "data_categories": categories,
        "redaction_version": redaction_version(str(classification["detections"])),
        "purpose": "Pre-publication brand review",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "retention": policy["retention"],
        "outcome": "completed",
    }
