from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.idempotency import cached, remember
from app.api.serialize import content_brief, iso
from app.models import Brand, ContentItem, ContentVersion
from app.schemas import ContentCreate, ContentRevision
from app.services import classify, media, passport, plans
from app.services.reviews import content_hash


router = APIRouter(prefix="/content", tags=["content"])


@router.get("")
def list_content(brand_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    stmt = select(ContentItem).where(ContentItem.org_id == ctx.org.id)
    if brand_id:
        stmt = stmt.where(ContentItem.brand_id == brand_id)
    items = list(ctx.db.scalars(stmt.order_by(ContentItem.created_at.desc())))
    return [content_brief(ctx.db, i) for i in items]


@router.post("", status_code=201)
async def create_content(
    payload: ContentCreate,
    ctx: Ctx = Depends(get_ctx),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    ctx.require("creator")
    replay = cached(ctx.db, ctx.org.id, idempotency_key, "content.create")
    if replay is not None:
        return replay
    brand = ctx.db.get(Brand, payload.brand_id)
    if brand is None or brand.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Brand not found in this workspace.")

    transcript = [seg.model_dump() for seg in payload.transcript if seg.text.strip()]
    body_text = payload.body_text
    if transcript:
        body_text = "\n".join(seg["text"] for seg in transcript)
    duration = payload.duration_s or (max((seg["end"] for seg in transcript), default=0.0) if transcript else 0.0)

    item = ContentItem(
        org_id=ctx.org.id,
        brand_id=brand.id,
        title=payload.title,
        channel=payload.channel,
        language=payload.language,
        campaign=payload.campaign,
        desired_cta=payload.desired_cta,
        audience=payload.audience or brand.audience,
        modality=payload.modality,
        created_by=ctx.user.id,
    )
    ctx.db.add(item)
    ctx.db.flush()
    version = ContentVersion(
        content_item_id=item.id,
        brand_id=brand.id,
        version=1,
        body_text=body_text,
        media_ref=payload.media_ref,
        content_hash=content_hash(body_text, payload.media_ref),
        sensitivity=payload.sensitivity,
        meta=payload.meta,
        transcript=transcript,
        duration_s=float(duration or 0.0),
        author_id=ctx.user.id,
    )
    ctx.db.add(version)
    ctx.db.commit()
    ctx.db.refresh(item)

    # classification runs here, once, and is stored with the version
    version = max(item.versions, key=lambda v: v.version)
    try:
        await classify.classify_content_version(ctx.db, version, brand)
    except Exception:
        pass  # a classification failure must never block submitting content

    ctx.db.refresh(item)
    result = content_brief(ctx.db, item)
    remember(ctx.db, ctx.org.id, idempotency_key, "content.create", result)
    ctx.db.commit()
    return result


@router.post("/extract")
async def extract(file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    """Document ingestion: normalise text out of a PDF, DOCX or plain-text upload.

    Unsupported formats get a clear message and an alternative path, never a
    silent failure.
    """
    ctx.require("creator")
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is larger than the 8 MB demo limit.")
    name = (file.filename or "").lower()
    text = ""
    try:
        if name.endswith(".pdf"):
            import io

            import pymupdf

            doc = pymupdf.open(stream=raw, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
        elif name.endswith(".docx"):
            import io

            from docx import Document as Docx

            d = Docx(io.BytesIO(raw))
            text = "\n".join(p.text for p in d.paragraphs)
        elif name.endswith((".txt", ".md", ".csv")):
            text = raw.decode("utf-8", errors="replace")
        else:
            raise HTTPException(
                status_code=415,
                detail=f"'{file.filename}' is not a supported format yet. Upload PDF, DOCX, TXT or paste the copy instead.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read that file: {exc}") from exc

    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="No text found. The file may be a scan; upload a text layer or paste the copy instead.",
        )
    return {"filename": file.filename, "characters": len(text), "text": text[:20000]}


@router.post("/{item_id}/classify")
async def reclassify(item_id: str, ctx: Ctx = Depends(get_ctx)):
    """Re-run classification for the latest version of a content item."""
    ctx.require("creator")
    item = ctx.db.get(ContentItem, item_id)
    if item is None or item.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Content not found.")
    brand = ctx.db.get(Brand, item.brand_id)
    version = max(item.versions, key=lambda v: v.version)
    result = await classify.classify_content_version(ctx.db, version, brand, force=True)
    return {"content_id": item.id, "version": version.version, "classification": result.model_dump()}


@router.get("/{item_id}")
def get_content(item_id: str, ctx: Ctx = Depends(get_ctx)):
    item = ctx.db.get(ContentItem, item_id)
    if item is None or item.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Content not found.")
    data = content_brief(ctx.db, item)
    data["versions"] = [
        {
            "id": v.id,
            "version": v.version,
            "body_text": v.body_text,
            "sensitivity": v.sensitivity,
            "hash": v.content_hash,
            "created_at": iso(v.created_at),
        }
        for v in sorted(item.versions, key=lambda v: v.version, reverse=True)
    ]
    return data


@router.post("/{item_id}/versions", status_code=201)
def add_version(item_id: str, payload: ContentRevision, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    item = ctx.db.get(ContentItem, item_id)
    if item is None or item.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Content not found.")
    latest = max(item.versions, key=lambda v: v.version) if item.versions else None
    invalidated = passport.invalidate_for_item(ctx.db, item.id, "New content version created")
    version = ContentVersion(
        content_item_id=item.id,
        brand_id=item.brand_id,
        version=(latest.version + 1) if latest else 1,
        body_text=payload.body_text,
        media_ref=latest.media_ref if latest else "",
        content_hash=content_hash(payload.body_text, latest.media_ref if latest else ""),
        sensitivity=latest.sensitivity if latest else "internal",
        meta=payload.meta or (latest.meta if latest else {}),
        author_id=ctx.user.id,
    )
    ctx.db.add(version)
    ctx.db.commit()
    return {
        "version": version.version,
        "version_id": version.id,
        "invalidated_clearances": [c.clearance_id for c in invalidated],
    }
