"""Runtime configuration for BrandSetGo.

Everything has a working default so the API boots with no .env at all.
The only optional values are the Sarvam credentials: without them the
review pipeline runs in deterministic demo mode (see services/llm.py).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BrandSetGo API"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./brandsetgo.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Sarvam AI gateway. Empty key => deterministic demo mode.
    sarvam_api_key: str = ""
    # a key file next to the app, so a host can mount a secret without env wiring
    sarvam_key_file: str = "sarvam.key"
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    # sarvam-105b is a reasoning model (~15s, reasoning tokens dominate the budget).
    # sarvam-105b-conversations answers structured JSON in well under a second.
    sarvam_model: str = "sarvam-105b-conversations"
    sarvam_reasoning_model: str = "sarvam-105b"
    # speech-to-text and text-to-speech live at the API root, not under /v1
    sarvam_stt_url: str = "https://api.sarvam.ai/speech-to-text"
    sarvam_region: str = "asia-south1 (in)"
    sarvam_timeout: float = 45.0
    sarvam_max_retries: int = 2
    sarvam_max_tokens: int = 1400
    # AI layers: classification always on when a key exists; the semantic
    # reviewer pass and AI rewrites can be switched off per deployment.
    ai_classification: bool = True
    ai_semantic_review: bool = True
    ai_rewrite: bool = True
    ai_rule_extraction: bool = True
    ai_legal_review: bool = True

    # ---- mail (optional: without SMTP everything still lands in the outbox) ----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "BrandSetGo <no-reply@brandsetgo.local>"
    public_base_url: str = "http://localhost:8000"

    # ---- abuse control ----
    rate_limit_enabled: bool = True
    login_attempts_per_minute: int = 10
    reviews_per_minute: int = 20

    upload_dir: str = "uploads"

    # ---- review runtime ----
    review_timeout_seconds: float = 120.0

    # ---- sessions ----
    # Leave empty to generate backend/.secret on first run (recommended).
    secret_key: str = ""
    secret_file: str = ".secret"
    session_days: int = 7
    cookie_name: str = "bs_session"
    cookie_secure: bool = False
    # The very first account created becomes the platform admin.
    first_user_is_admin: bool = True
    # Demo data is never loaded automatically; run `python -m app.scripts.seed_demo`.
    seed_on_startup: bool = False

    # Risk routing defaults (org overrides live in risk_policies table)
    fast_track_max: int = 25
    manager_max: int = 70

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def live_models(self) -> bool:
        return bool(self.api_key)

    @property
    def api_key(self) -> str:
        """Env var first, then backend/sarvam.key, then whatever .env provided.

        This is the one place that answers "is there a key?", so a deployment can
        supply it as an env var, a mounted secret file, or a local .env without
        any code change.
        """
        if self.sarvam_api_key.strip():
            return self.sarvam_api_key.strip()
        try:
            from pathlib import Path

            candidate = Path(self.sarvam_key_file)
            if not candidate.is_absolute():
                candidate = Path(__file__).resolve().parents[2] / candidate
            if candidate.exists():
                return candidate.read_text().strip()
        except OSError:
            pass
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
