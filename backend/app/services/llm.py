"""Thin compatibility layer over the Sarvam client.

Callers that only need a sentence of wording use `phrase()`; everything that
needs structured output goes through `sarvam.chat_json` directly.
"""
from __future__ import annotations

from app.core.config import settings
from app.services import sarvam


def mode() -> str:
    return sarvam.model_name()


async def phrase(system: str, user: str, fallback: str) -> str:
    """Return model wording when available, otherwise the deterministic text."""
    if not sarvam.enabled():
        return fallback
    result = await sarvam.chat_json(system, user, max_tokens=220)
    if result.ok and result.data:
        for key in ("text", "explanation", "sentence"):
            value = result.data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:400]
    return fallback


def disclosure_region() -> str:
    return settings.sarvam_region if sarvam.enabled() else "local (no transfer)"
