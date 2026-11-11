"""Visual checker: approved assets, palette, logo use, layout heuristics."""
from __future__ import annotations

from app.schemas import FindingDraft
from app.services.agents.base import AgentContext


def run(ctx: AgentContext) -> list[FindingDraft]:
    rule = ctx.rule("visual")
    code = rule.code if rule else "R-VISUAL"
    refs = ctx.rule_ref("visual")

    if not ctx.meta.get("media_ref") and ctx.meta.get("modality", "text") == "text":
        return [
            FindingDraft(
                agent="visual",
                rule_code=code,
                title="No visual elements",
                severity="low",
                confidence=0.95,
                status="pass",
                explanation="Text-only submission, so logo, palette and layout checks do not apply.",
                evidence_refs=refs or ["Asset library"],
            )
        ]

    asset_hash = ctx.meta.get("asset_hash", "")
    asset = next((a for a in ctx.assets if asset_hash and a.content_hash == asset_hash), None)
    out: list[FindingDraft] = []

    if asset is None:
        out.append(
            FindingDraft(
                agent="visual",
                rule_code=code,
                title="Asset not in approved library",
                severity="medium",
                confidence=0.5,
                status="needs_human_review",
                explanation="This file is not a known approved asset, so palette and logo use need a human look.",
                evidence_refs=["Asset library"] + refs[:1],
            )
        )
        return out

    image = ctx.meta.get("image") or {}
    if image.get("palette"):
        # real pixels from the upload, not asset metadata
        brand_palette = {c.lower().lstrip("#") for c in (ctx.brand.palette or {}).get("colors", [])}
        if brand_palette:
            off = [c for c in image["palette"] if c.lower().lstrip("#") not in brand_palette]
            if off:
                out.append(
                    FindingDraft(
                        agent="visual",
                        rule_code=code,
                        title="Off-palette colour in the image",
                        severity="medium",
                        confidence=0.82,
                        status="confirmed",
                        explanation=(
                            f"{len(off)} colour(s) measured from the uploaded image fall outside the approved "
                            f"palette: {', '.join(off[:3])}."
                        ),
                        evidence_refs=["Approved palette"] + refs[:1],
                    )
                )
        if not out:
            out.append(
                FindingDraft(
                    agent="visual",
                    rule_code=code,
                    title="Visual correct",
                    severity="low",
                    confidence=0.86,
                    status="pass",
                    explanation="Measured palette sits inside the approved brand colours.",
                    evidence_refs=["Approved palette"] + refs[:1],
                )
            )
        return out

    brand_palette = {c.lower() for c in (ctx.brand.palette or {}).get("colors", [])}
    if brand_palette:
        off = [c for c in asset.palette if c.lower() not in brand_palette]
        if off:
            out.append(
                FindingDraft(
                    agent="visual",
                    rule_code=code,
                    title="Off-palette colour",
                    severity="medium",
                    confidence=0.8,
                    status="confirmed",
                    explanation=f"{len(off)} colour(s) fall outside the approved palette: {', '.join(off[:3])}.",
                    evidence_refs=["Approved palette"] + refs[:1],
                )
            )
    if not asset.has_logo:
        out.append(
            FindingDraft(
                agent="visual",
                rule_code=code,
                title="Brand logo missing",
                severity="high",
                confidence=0.9,
                status="confirmed",
                explanation="The logo lockup is missing from this asset.",
                evidence_refs=["Logo lockup guideline"] + refs[:1],
            )
        )
    if not out:
        out.append(
            FindingDraft(
                agent="visual",
                rule_code=code,
                title="Visual correct",
                severity="low",
                confidence=0.86,
                status="pass",
                explanation="Approved asset, on-palette colours and correct logo lockup.",
                evidence_refs=["Asset library"] + refs[:1],
            )
        )
    return out
