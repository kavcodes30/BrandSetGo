"""AI content classification (Sarvam).

Classifies a submission before any checker runs: language, content type, brand
category, audience, sensitivity, personal data, extractable claims, promises
made, tone and risk hints.

Guards that make the output trustworthy:
* every claim the model returns must be an exact substring of the copy — a
  paraphrase is dropped, never silently "corrected";
* the language is cross-checked against the script actually used;
* the sensitivity label can only be raised, never lowered, by the model;
* personal-data categories are the union of the model's list and a
  deterministic detector.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import sarvam

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")

SENSITIVITY_ORDER = ["public", "internal", "confidential", "restricted"]
MAX_CHARS = 4000

SYSTEM = (
    "You are the content classifier inside BrandSetGo, an Indian brand-governance platform. "
    "You classify marketing and brand content before it is reviewed. "
    "Return ONLY a JSON object that matches the requested schema. No prose, no code fences. "
    "Every claim you return must quote an exact substring of the content."
)

SCHEMA = """{
  "language": "en|hi|mr|other",
  "content_type": "ad|product_page|social_post|email|blog|document|other",
  "category": "perfume|skincare|beauty|fashion|food|finance|health|tech|education|other",
  "audience": "short phrase",
  "sensitivity": "public|internal|confidential|restricted",
  "pii": ["email|phone|card|aadhaar|none"],
  "claims": [{"text": "exact substring", "type": "duration|efficacy|clinical|price|absolute|ingredient|other", "verifiable": true}],
  "promises_made": ["short phrase"],
  "tone": "short phrase",
  "risk_hints": ["short phrase"],
  "confidence": 0.0
}"""


class ClaimOut(BaseModel):
    text: str
    type: str = "other"
    verifiable: bool = True


class Classification(BaseModel):
    language: str = "en"
    content_type: str = "other"
    category: str = "other"
    audience: str = ""
    sensitivity: str = "internal"
    pii: list[str] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)
    promises_made: list[str] = Field(default_factory=list)
    tone: str = ""
    risk_hints: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source: Literal["sarvam", "deterministic"] = "deterministic"
    model: str = "deterministic-demo"
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    dropped_claims: int = 0
    notes: list[str] = Field(default_factory=list)


def script_language(text: str) -> str:
    dev = len(DEVANAGARI.findall(text))
    lat = len(LATIN.findall(text))
    if dev == 0 and lat == 0:
        return "other"
    if dev > lat * 0.5:
        return "devanagari"
    return "en"


def detect_pii(text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in (("email", EMAIL), ("phone", PHONE), ("card", CARD), ("aadhaar", AADHAAR)):
        if pattern.search(text):
            found.append(label)
    return found


def raise_label(current: str, floor: str) -> str:
    i = SENSITIVITY_ORDER.index(current) if current in SENSITIVITY_ORDER else 1
    j = SENSITIVITY_ORDER.index(floor) if floor in SENSITIVITY_ORDER else 1
    return SENSITIVITY_ORDER[max(i, j)]


def _fallback(text: str, declared: str, channel: str, sector: str) -> Classification:
    pii = detect_pii(text)
    return Classification(
        language="en" if script_language(text) == "en" else "hi",
        content_type="social_post" if "instagram" in channel else "other",
        category=sector or "other",
        audience="",
        sensitivity=raise_label(declared, "confidential" if pii else declared),
        pii=pii or ["none"],
        claims=[],
        tone="",
        risk_hints=["classification ran without a model"],
        confidence=0.3,
        source="deterministic",
        model="deterministic-demo",
    )


def _validate(
    data: dict,
    text: str,
    declared: str,
    brand_languages: list[str],
    latency_ms: int,
    declared_language: str = "en",
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> Classification:
    notes: list[str] = []
    lowered = text.lower()

    claims: list[ClaimOut] = []
    dropped = 0
    for item in data.get("claims") or []:
        if not isinstance(item, dict):
            continue
        span = str(item.get("text") or "").strip()
        if not span:
            continue
        # hallucination guard: the quote must exist in the copy
        if span.lower() not in lowered:
            dropped += 1
            continue
        claims.append(
            ClaimOut(
                text=span,
                type=str(item.get("type") or "other"),
                verifiable=bool(item.get("verifiable", True)),
            )
        )
    if dropped:
        notes.append(f"{dropped} model claim(s) dropped: not an exact substring of the copy")

    language = str(data.get("language") or "en").lower()
    if language not in {"en", "hi", "mr", "other"}:
        language = "other"
    script = script_language(text)
    if script == "devanagari" and language in ("en", "other"):
        if declared_language in ("hi", "mr"):
            language = declared_language
        else:
            devanagari_brands = [l for l in brand_languages if l in ("hi", "mr")]
            language = devanagari_brands[0] if devanagari_brands else "hi"
        notes.append("language corrected from script: the copy is Devanagari")
    if script == "en" and language in ("hi", "mr") and not DEVANAGARI.search(text):
        language = "en"
        notes.append("language corrected from script: no Devanagari characters present")

    model_pii = [p for p in (data.get("pii") or []) if p and p != "none"]
    pii = sorted(set(model_pii) | set(detect_pii(text)))

    declared_floor = "confidential" if pii else declared
    sensitivity = raise_label(str(data.get("sensitivity") or declared).lower(), declared_floor)
    if sensitivity != str(data.get("sensitivity") or "").lower():
        notes.append(f"sensitivity raised to {sensitivity}")

    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.7)))
    except (TypeError, ValueError):
        confidence = 0.7

    return Classification(
        language=language,
        content_type=str(data.get("content_type") or "other"),
        category=str(data.get("category") or "other"),
        audience=str(data.get("audience") or "")[:160],
        sensitivity=sensitivity,
        pii=pii or ["none"],
        claims=claims,
        promises_made=[str(p)[:160] for p in (data.get("promises_made") or [])][:8],
        tone=str(data.get("tone") or "")[:120],
        risk_hints=[str(r)[:160] for r in (data.get("risk_hints") or [])][:6],
        confidence=confidence,
        source="sarvam",
        model=sarvam.model_name(),
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dropped_claims=dropped,
        notes=notes,
    )


async def classify(
    text: str,
    *,
    declared_sensitivity: str = "internal",
    channel: str = "instagram_caption",
    sector: str = "",
    brand_languages: list[str] | None = None,
    declared_language: str = "en",
) -> Classification:
    """Classify one submission. Always returns a usable object."""
    languages = brand_languages or ["en"]
    body = (text or "").strip()
    if not body:
        return _fallback("", declared_sensitivity, channel, sector)

    if not (sarvam.enabled() and settings.ai_classification):
        return _fallback(body, declared_sensitivity, channel, sector)

    user = (
        f"Schema:\n{SCHEMA}\n\n"
        f"Channel: {channel}\nBrand sector: {sector or 'unknown'}\n"
        f"Declared sensitivity: {declared_sensitivity}\n"
        f"Brand languages: {', '.join(languages)}\n\n"
        f"CONTENT:\n<<<{body[:MAX_CHARS]}>>>"
    )
    result = await sarvam.chat_json(SYSTEM, user, max_tokens=900)
    if not result.ok or not result.data:
        fallback = _fallback(body, declared_sensitivity, channel, sector)
        fallback.notes.append(f"model unavailable ({result.error}); deterministic fallback used")
        fallback.latency_ms = result.latency_ms
        return fallback
    return _validate(
        result.data,
        body,
        declared_sensitivity,
        languages,
        result.latency_ms,
        declared_language,
        result.tokens_in,
        result.tokens_out,
    )


async def classify_content_version(db, content, brand, *, force: bool = False) -> Classification:
    """Classify a content version once and keep the result on it.

    Classification is a property of the content, not of the review, so it runs at
    ingest: a review then reads the stored answer and spends its API budget on the
    checkers. Re-running is explicit (`force=True`) or automatic when the content
    hash changed.
    """
    meta = dict(content.meta or {})
    stored = meta.get("classification") or {}
    if stored and not force and stored.get("content_hash") == content.content_hash:
        data = {k: v for k, v in stored.items() if k != "content_hash"}
        try:
            return Classification(**data)
        except Exception:
            pass  # stored shape from an older version: recompute

    result = await classify(
        content.body_text,
        declared_sensitivity=content.sensitivity,
        channel=content.item.channel,
        sector=brand.sector,
        brand_languages=brand.languages or ["en"],
        declared_language=content.item.language,
    )
    meta["classification"] = {**result.model_dump(), "content_hash": content.content_hash}
    content.meta = meta
    content.sensitivity = raise_label(content.sensitivity, result.sensitivity)
    result.sensitivity = content.sensitivity
    db.commit()
    return result
