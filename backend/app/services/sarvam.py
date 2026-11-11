"""Sarvam AI client.

One place that talks to the Sarvam gateway, so every caller gets the same
timeout, retry, JSON-extraction, token-accounting and circuit-breaker behaviour.

Design rules:
* A model answer is data, never an instruction. Callers validate it.
* Nothing here invents evidence: callers pass the rule set and the client only
  returns what the model said about it.
* If the gateway is unavailable the platform degrades to deterministic checks
  instead of failing the review.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

log = logging.getLogger("brandsetgo.sarvam")

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class SarvamResult:
    ok: bool
    data: dict | None = None
    text: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None
    cached: bool = False

    @property
    def tokens_in(self) -> int:
        return int((self.usage or {}).get("prompt_tokens") or 0)

    @property
    def tokens_out(self) -> int:
        return int((self.usage or {}).get("completion_tokens") or 0)


@dataclass
class _State:
    calls: int = 0
    failures: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_latency_ms: int = 0
    open_until: float = 0.0
    last_error: str | None = None
    last_latency_ms: int = 0


_state = _State()
_cache: dict[str, tuple[float, SarvamResult]] = {}
CACHE_TTL = 300.0


def api_key() -> str:
    return settings.api_key


def enabled() -> bool:
    return bool(api_key())


def model_name() -> str:
    return settings.sarvam_model if enabled() else "deterministic-demo"


def status() -> dict:
    return {
        "enabled": enabled(),
        "model": model_name(),
        "base_url": settings.sarvam_base_url,
        "region": settings.sarvam_region if enabled() else "local (no transfer)",
        "calls": _state.calls,
        "failures": _state.failures,
        "tokens_in": _state.tokens_in,
        "tokens_out": _state.tokens_out,
        "avg_latency_ms": int(_state.total_latency_ms / _state.calls) if _state.calls else 0,
        "last_latency_ms": _state.last_latency_ms,
        "circuit_open": time.time() < _state.open_until,
        "last_error": _state.last_error,
        "layers": {
            "classification": settings.ai_classification,
            "semantic_review": settings.ai_semantic_review,
            "rewrite": settings.ai_rewrite,
            "rule_extraction": settings.ai_rule_extraction,
        },
    }


def _cache_key(system: str, user: str, model: str) -> str:
    raw = f"{model}::{system}::{user}".encode()
    return hashlib.sha256(raw).hexdigest()


def extract_json(text: str) -> dict | None:
    """Pull the first balanced JSON object out of a model reply."""
    if not text:
        return None
    cleaned = FENCE.sub("", text).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


async def chat_json(
    system: str,
    user: str,
    *,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    model: str | None = None,
    use_cache: bool = True,
) -> SarvamResult:
    """Call Sarvam and return a validated JSON object (or a clean failure)."""
    if not enabled():
        return SarvamResult(ok=False, error="no-api-key")

    now = time.time()
    if now < _state.open_until:
        return SarvamResult(ok=False, error="circuit-open")

    chosen = model or settings.sarvam_model
    key = _cache_key(system, user, chosen)
    if use_cache and key in _cache:
        ts, cached = _cache[key]
        if now - ts < CACHE_TTL:
            return SarvamResult(**{**cached.__dict__, "cached": True})

    payload = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens or settings.sarvam_max_tokens,
    }
    headers = {
        "api-subscription-key": api_key(),
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    url = f"{settings.sarvam_base_url.rstrip('/')}/chat/completions"

    last_error = ""
    for attempt in range(settings.sarvam_max_retries + 1):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.sarvam_timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
            latency = int((time.perf_counter() - started) * 1000)

            if resp.status_code >= 500 or resp.status_code == 429:
                last_error = f"HTTP {resp.status_code}"
                await asyncio.sleep(0.4 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                detail = resp.text[:200]
                last_error = f"HTTP {resp.status_code}: {detail}"
                break

            body = resp.json()
            message = (body.get("choices") or [{}])[0].get("message") or {}
            content = message.get("content") or ""
            usage = body.get("usage") or {}
            parsed = extract_json(content)

            _state.calls += 1
            _state.tokens_in += int(usage.get("prompt_tokens") or 0)
            _state.tokens_out += int(usage.get("completion_tokens") or 0)
            _state.total_latency_ms += latency
            _state.last_latency_ms = latency

            result = SarvamResult(
                ok=parsed is not None,
                data=parsed,
                text=content,
                usage=usage,
                latency_ms=latency,
                error=None if parsed is not None else "unparseable-json",
            )
            if use_cache and parsed is not None:
                _cache[key] = (time.time(), result)
            return result

        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"{type(exc).__name__}"
            await asyncio.sleep(0.4 * (attempt + 1))
        except Exception as exc:  # pragma: no cover - defensive
            last_error = f"{type(exc).__name__}: {exc}"
            break

    _state.failures += 1
    _state.last_error = last_error
    if _state.failures >= 3:
        _state.open_until = time.time() + 60.0
        _state.failures = 0
        log.warning("Sarvam circuit opened after repeated failures: %s", last_error)
    return SarvamResult(ok=False, error=last_error)


async def health() -> dict:
    """Cheap liveness probe used by the Privacy Center and /health."""
    if not enabled():
        return {"ok": False, "reason": "no-api-key", "model": model_name()}
    started = time.perf_counter()
    result = await chat_json(
        "Reply with JSON only.",
        'Return {"ok": true} and nothing else.',
        max_tokens=40,
        use_cache=False,
    )
    return {
        "ok": result.ok,
        "model": model_name(),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "error": result.error,
    }


def reset_state() -> None:
    """Used by tests."""
    global _state
    _state = _State()
    _cache.clear()
