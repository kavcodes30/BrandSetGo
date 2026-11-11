"""BrandSetGo API entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import (
    admin,
    approvals,
    auth,
    billing,
    brands,
    content,
    legal,
    media,
    misc,
    passport_api,
    privacy_api,
    reviews,
    workspace,
)
from app.core.config import settings
from app.core.db import SessionLocal, init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("brandsetgo")


def _report_ai() -> None:
    """One line at boot so you can see whether the model is live."""
    if sarvam.enabled():
        print(
            f"[BrandSetGo] Sarvam: connected · model={settings.sarvam_model} · "
            f"key from {'env' if settings.sarvam_api_key else 'file'}",
            flush=True,
        )
    else:
        print("[BrandSetGo] Sarvam: no key · deterministic mode", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_on_startup:
        from app.services.seed import seed_demo

        db = SessionLocal()
        try:
            result = await seed_demo(db)
            log.info("demo seed: %s", result)
        finally:
            db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Self-service, privacy-aware brand governance: evidence-linked review, visible disagreement, intent-preserving rewrites and version-locked clearance.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, billing.router, admin.router, media.assets_router, workspace.router, legal.router, media.router,
          brands.router, content.router, reviews.router, reviews.patches_router,
          approvals.router, passport_api.router, passport_api.verify_router,
          privacy_api.router, misc.router):
    app.include_router(r, prefix=settings.api_prefix)


WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@app.get("/health")
def health():
    from app.services import sarvam

    return {
        "status": "ok",
        "app": settings.app_name,
        "live_models": sarvam.enabled(),
        "key_source": "env" if settings.sarvam_api_key else ("file" if sarvam.api_key() else "none"),
        "model": sarvam.model_name(),
    }


# The app is plain HTML/CSS/JS: no build step, no Node, no bundler. FastAPI serves
# it from the same origin as the API, so there is no CORS surface in production.
if (WEB_DIR / "index.html").exists():
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
