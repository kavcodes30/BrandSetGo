"""Media ingestion: audio transcription and transcript upload."""
from __future__ import annotations

import hashlib
import pathlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Ctx, get_ctx
from app.core.config import settings
from app.models import Asset, Brand
from app.schemas import TranscriptUpload
from app.services import images, media

router = APIRouter(prefix="/content", tags=["media"])
assets_router = APIRouter(prefix="/assets", tags=["media"])

MAX_BYTES = 25 * 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _upload_root() -> pathlib.Path:
    root = pathlib.Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post("/upload-image", status_code=201)
async def upload_image(
    brand_id: str = Form(...),
    alt_text: str = Form(""),
    file: UploadFile = File(...),
    ctx: Ctx = Depends(get_ctx),
):
    """Store an image, measure it from pixels, and return the analysis.

    The analysis is what the visual and accessibility checkers use, so an image
    is judged on its real colours rather than on metadata someone typed in.
    """
    ctx.require("creator")
    brand = ctx.db.get(Brand, brand_id)
    if brand is None or brand.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace.")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Images over 25 MB are not supported.")
    suffix = IMAGE_TYPES.get((file.content_type or "").lower())
    if suffix is None:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPEG, WEBP or GIF image.")

    try:
        analysis = images.analyze(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read that image: {exc}") from exc

    digest = hashlib.sha256(data).hexdigest()[:32]
    asset = Asset(
        brand_id=brand.id,
        name=file.filename or f"upload{suffix}",
        kind="image",
        content_hash=digest,
        palette=analysis["palette"],
        has_logo=True,
        alt_text=alt_text.strip()[:300],
        width=analysis["width"],
        height=analysis["height"],
    )
    ctx.db.add(asset)
    ctx.db.flush()

    stored = _upload_root() / f"{asset.id}{suffix}"
    stored.write_bytes(data)

    ctx.db.commit()
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "analysis": analysis,
        "off_palette": images.palette_delta(analysis["palette"], (brand.palette or {}).get("colors", [])),
    }


@assets_router.get("/{asset_id}/file")
def asset_file(asset_id: str, ctx: Ctx = Depends(get_ctx)):
    asset = ctx.db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    brand = ctx.db.get(Brand, asset.brand_id)
    if brand is None or brand.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Asset not found.")
    for suffix in (".png", ".jpg", ".webp", ".gif"):
        candidate = _upload_root() / f"{asset.id}{suffix}"
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="The stored file is missing.")


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    """Audio (or video, when ffmpeg is present) to timestamped segments."""
    ctx.require("creator")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Files over 25 MB are not supported in this build.")
    result = await media.transcribe(data, file.filename or "upload", file.content_type or "")
    if not result.get("ok"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": result.get("reason", "transcription-failed"),
                "message": result.get("message", "Could not transcribe that file."),
                "alternative": "Paste the transcript (SRT, VTT or timestamped text) instead.",
            },
        )
    return {
        "filename": file.filename,
        "segments": result["segments"],
        "duration_s": result["duration_s"],
        "language": result.get("language", ""),
        "engine": result.get("engine", ""),
        "timing": result.get("timing", "estimated"),
        "converted_audio": result.get("converted_audio", False),
        "word_count": result.get("word_count", 0),
    }


@router.post("/transcript")
def parse_transcript(payload: TranscriptUpload, ctx: Ctx = Depends(get_ctx)):
    """Parse an SRT/VTT/timestamped-text transcript into segments."""
    ctx.require("creator")
    segments = media.parse_transcript(payload.content, payload.format)
    if not segments:
        raise HTTPException(status_code=422, detail="No timestamped lines were found in that transcript.")
    return {
        "segments": segments,
        "duration_s": round(max(s["end"] for s in segments), 2),
        "engine": "transcript",
        "word_count": sum(len(s["text"].split()) for s in segments),
    }
