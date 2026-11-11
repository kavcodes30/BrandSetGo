"""Password hashing and signed session tokens, standard library only.

No third-party auth dependency: PBKDF2-HMAC-SHA256 for passwords, an
HMAC-SHA256 signed token for the session cookie. The signing secret is read
from the environment or generated once into `backend/.secret`, so no secret is
ever committed and sessions survive a restart.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from app.core.config import settings

PBKDF2_ROUNDS = 210_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * settings.session_days


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_secret() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    path = Path(settings.secret_file)
    if path.exists():
        return path.read_bytes()
    secret = secrets.token_urlsafe(48).encode()
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64d(salt_b64), int(rounds))
        return hmac.compare_digest(digest, _b64d(digest_b64))
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, *, extra: dict | None = None, ttl_seconds: int | None = None) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + (ttl_seconds or TOKEN_TTL_SECONDS), **(extra or {})}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(signing_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64e(signature)}"


def decode_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    body, signature = token.split(".", 1)
    expected = hmac.new(signing_secret(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_b64d(signature), expected):
            return None
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("Use at least 8 characters.")
    if password.isalpha() or password.isdigit():
        problems.append("Mix letters with a number or symbol.")
    return problems
