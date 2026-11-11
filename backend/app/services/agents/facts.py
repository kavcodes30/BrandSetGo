"""Facts / Evidence checker: product quantities, prices, verified statements."""
from __future__ import annotations

import re

from app.schemas import FindingDraft, SuggestedPatch
from app.services.agents.base import AgentContext

SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(ml|mls?|millilitres?|g|gm|grams?|kg)\b", re.I)
PRICE = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", re.I)
UNIT_ALIASES = {"mls": "ml", "millilitre": "ml", "millilitres": "ml", "gm": "g", "gram": "g", "grams": "g"}


def _norm_unit(u: str) -> str:
    u = u.lower()
    return UNIT_ALIASES.get(u, u)


def run(ctx: AgentContext) -> list[FindingDraft]:
    rule = ctx.rule("facts")
    code = rule.code if rule else "R-FACTS"
    refs = ctx.rule_ref("facts")
    out: list[FindingDraft] = []
    product = ctx.product_mentioned()

    if product is None:
        return [
            FindingDraft(
                agent="facts",
                rule_code=code,
                title="No product record matched",
                severity="low",
                confidence=0.4,
                status="inconclusive",
                explanation="No product record matched this copy, so quantities and prices could not be verified.",
                evidence_refs=["Product catalogue"] + refs[:1],
            )
        ]

    sheet = f"{product.sheet_ref or 'Product sheet'} v{product.sheet_page}, page {product.sheet_page}"
    attrs = product.attributes or {}

    for m in SIZE.finditer(ctx.content):
        stated, unit = float(m.group(1)), _norm_unit(m.group(2))
        expected = attrs.get("volume_ml") if unit == "ml" else attrs.get("weight_g")
        if expected is None:
            continue
        if abs(stated - float(expected)) > 0.01:
            out.append(
                FindingDraft(
                    agent="facts",
                    rule_code=code,
                    title="Product size mismatch",
                    severity="medium",
                    confidence=0.94,
                    status="confirmed",
                    span_text=m.group(0),
                    explanation=(
                        f"Size says {int(stated) if stated.is_integer() else stated} {unit}, "
                        f"but the product sheet says {int(float(expected))} {unit}."
                    ),
                    evidence_refs=[f"Evidence: {sheet}"] + refs[:1],
                    suggested_patch=SuggestedPatch(
                        replacement=f"{int(float(expected))} {unit}",
                        reason="Matches the verified product sheet.",
                        rule_code=code,
                    ),
                )
            )

    for m in PRICE.finditer(ctx.content):
        stated = float(m.group(1).replace(",", ""))
        expected = attrs.get("price_inr")
        if expected is None:
            continue
        if abs(stated - float(expected)) > 0.5:
            out.append(
                FindingDraft(
                    agent="facts",
                    rule_code=code,
                    title="Price mismatch",
                    severity="high",
                    confidence=0.92,
                    status="confirmed",
                    span_text=m.group(0),
                    explanation=f"Price in copy is ₹{int(stated)}, but the approved price list says ₹{int(float(expected))}.",
                    evidence_refs=[f"Evidence: {sheet}"] + refs[:1],
                    suggested_patch=SuggestedPatch(
                        replacement=f"₹{int(float(expected))}",
                        reason="Matches the approved price list.",
                        rule_code=code,
                    ),
                )
            )

    if not out:
        out.append(
            FindingDraft(
                agent="facts",
                rule_code=code,
                title="Product facts verified",
                severity="low",
                confidence=0.88,
                status="pass",
                explanation=f"Quantities and prices match {sheet}.",
                evidence_refs=[f"Evidence: {sheet}"] + refs[:1],
            )
        )
    return out
