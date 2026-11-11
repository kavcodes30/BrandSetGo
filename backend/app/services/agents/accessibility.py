"""Accessibility checker: measurable contrast, alt text, document structure."""
from __future__ import annotations

from app.schemas import FindingDraft
from app.services.agents.base import AgentContext, contrast_ratio

MIN_TEXT_CONTRAST = 4.5


def run(ctx: AgentContext) -> list[FindingDraft]:
    rule = ctx.rule("accessibility")
    code = rule.code if rule else "R-A11Y"
    refs = ctx.rule_ref("accessibility")
    out: list[FindingDraft] = []

    palette = ctx.brand.palette or {}
    image = ctx.meta.get("image") or {}
    ratio = ctx.meta.get("contrast_ratio") or image.get("contrast_ratio")
    if ratio is None and palette.get("text") and palette.get("background"):
        ratio = contrast_ratio(str(palette["text"]), str(palette["background"]))

    has_visual = bool(ctx.meta.get("media_ref")) or ctx.meta.get("modality", "text") != "text"

    if ratio is not None and float(ratio) < MIN_TEXT_CONTRAST:
        out.append(
            FindingDraft(
                agent="accessibility",
                rule_code=code,
                title="Text contrast below minimum",
                severity="medium",
                confidence=0.97,
                status="confirmed",
                span_text="contrast",
                explanation=f"Measured contrast is {ratio}:1, below the {MIN_TEXT_CONTRAST}:1 minimum for body text.",
                evidence_refs=["WCAG 2.1 AA 1.4.3"] + refs[:1],
            )
        )

    if image.get("likely_text_heavy") and image.get("contrast_ratio") is None:
        out.append(
            FindingDraft(
                agent="accessibility",
                rule_code=code,
                title="Text-heavy image with no measurable text colour",
                severity="medium",
                confidence=0.6,
                status="needs_human_review",
                explanation="This image looks text-heavy, but no single text colour could be isolated to measure contrast.",
                evidence_refs=["WCAG 2.1 AA 1.4.3"] + refs[:1],
            )
        )

    if has_visual:
        asset = next(
            (a for a in ctx.assets if a.content_hash and a.content_hash == ctx.meta.get("asset_hash")), None
        )
        alt = ctx.meta.get("alt_text") or (asset.alt_text if asset else "")
        if not alt:
            out.append(
                FindingDraft(
                    agent="accessibility",
                    rule_code=code,
                    title="Missing alternative text",
                    severity="medium",
                    confidence=0.88,
                    status="confirmed",
                    explanation="This asset has no alternative text, so screen-reader users get nothing from it.",
                    evidence_refs=["WCAG 2.1 AA 1.1.1"] + refs[:1],
                )
            )

    if not out:
        out.append(
            FindingDraft(
                agent="accessibility",
                rule_code=code,
                title="Accessibility checks passed",
                severity="low",
                confidence=0.9,
                status="pass",
                explanation=(
                    f"Contrast {ratio}:1 meets AA."
                    if ratio is not None
                    else "No measurable contrast or alt-text target in this submission."
                ),
                evidence_refs=["WCAG 2.1 AA"] + refs[:1],
            )
        )
    return out
