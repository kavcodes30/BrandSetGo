"""The legal guideline library and a stateless copy scanner."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Ctx, get_ctx
from app.legal import checker
from app.legal import guidelines as G

router = APIRouter(prefix="/legal", tags=["legal"])


class LegalPreview(BaseModel):
    text: str
    sector: str = ""
    channel: str = "instagram_caption"
    language: str = "en"


@router.get("/guidelines")
def catalogue(ctx: Ctx = Depends(get_ctx)):
    return {
        "registry_version": G.REGISTRY_VERSION,
        "disclaimer": G.DISCLAIMER,
        "guidelines": G.catalogue(),
    }


@router.get("/guidelines/{code}")
def guideline(code: str, ctx: Ctx = Depends(get_ctx)):
    item = G.get(code)
    if item is None:
        raise HTTPException(status_code=404, detail="No guideline with that code.")
    return {
        "code": item.code,
        "title": item.title,
        "authority": item.authority,
        "citation": item.citation,
        "obligation": item.obligation,
        "severity": item.severity,
        "remediation": item.remediation,
        "sectors": list(item.sectors),
        "channels": list(item.channels),
        "tags": list(item.tags),
    }


@router.post("/preview")
def preview(payload: LegalPreview, ctx: Ctx = Depends(get_ctx)):
    """Scan copy against the registry without creating a review."""
    findings = checker.scan(
        payload.text,
        sector=payload.sector,
        channel=payload.channel,
        language=payload.language,
    )
    return {
        "registry_version": G.REGISTRY_VERSION,
        "disclaimer": G.DISCLAIMER,
        "findings": [f.model_dump() for f in findings],
        "checked": [g.code for g in G.applicable(payload.sector, payload.channel)],
    }
