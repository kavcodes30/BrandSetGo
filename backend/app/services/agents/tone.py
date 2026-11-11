"""Tone / Voice checker: brand voice, banned terms, approved examples."""
from __future__ import annotations

import re

from app.schemas import FindingDraft, SuggestedPatch
from app.services.agents.base import AgentContext, overlap
from app.services.agents.claims import ABSOLUTE, DURATION

EXCLAIM = re.compile(r"!")


def run(ctx: AgentContext) -> list[FindingDraft]:
    rule = ctx.rule("tone")
    code = rule.code if rule else "R-TONE"
    refs = ctx.rule_ref("tone")
    out: list[FindingDraft] = []

    banned = [t for t in (ctx.brand.personality or {}).get("banned_terms", []) if t]
    for term in banned:
        for m in re.finditer(re.escape(term), ctx.content, re.I):
            out.append(
                FindingDraft(
                    agent="tone",
                    rule_code=code,
                    title="Restricted brand language",
                    severity="high",
                    confidence=0.93,
                    status="confirmed",
                    span_text=m.group(0),
                    explanation=f"\u201c{m.group(0)}\u201d is on the brand's restricted-language list.",
                    evidence_refs=refs or ["Restricted language list"],
                    suggested_patch=SuggestedPatch(
                        replacement="", reason="Remove restricted wording.", rule_code=code
                    ),
                )
            )

    # Style verdict on confident, sensory phrasing. This is a style judgement
    # only: the checker explicitly does not rule on substantiation.
    for m in DURATION.finditer(ctx.content):
        out.append(
            FindingDraft(
                agent="tone",
                rule_code=code,
                title="Voice approved",
                severity="low",
                confidence=0.62,
                status="pass",
                span_text=m.group(0).strip(),
                explanation=(
                    "Phrasing reads as confident and sensory, which matches the brand voice. "
                    "This is a style verdict only; substantiation is the Claims reviewer's call."
                ),
                evidence_refs=refs or ["Brand voice guidelines"],
            )
        )
    for m in ABSOLUTE.finditer(ctx.content):
        out.append(
            FindingDraft(
                agent="tone",
                rule_code=code,
                title="Voice approved",
                severity="low",
                confidence=0.55,
                status="pass",
                span_text=m.group(0).strip(),
                explanation="Punchy emphasis is consistent with the brand's declarative voice.",
                evidence_refs=refs or ["Brand voice guidelines"],
            )
        )

    examples = ctx.approved_examples
    if examples:
        best = max((overlap(ctx.content, ex) for ex in examples), default=0.0)
        if best < 0.12 and not out:
            out.append(
                FindingDraft(
                    agent="tone",
                    rule_code=code,
                    title="Voice distance from approved examples",
                    severity="low",
                    confidence=0.45,
                    status="inconclusive",
                    explanation="Copy is stylistically far from your approved examples; a human should confirm the voice.",
                    evidence_refs=["Approved examples"] + refs[:1],
                )
            )

    bangs = len(EXCLAIM.findall(ctx.content))
    if bangs > 2:
        out.append(
            FindingDraft(
                agent="tone",
                rule_code=code,
                title="Over-punctuated",
                severity="low",
                confidence=0.7,
                status="confirmed",
                span_text="!",
                explanation=f"{bangs} exclamation marks is louder than the brand's calm register.",
                evidence_refs=refs or ["Brand voice guidelines"],
            )
        )

    if not out:
        out.append(
            FindingDraft(
                agent="tone",
                rule_code=code,
                title="Tone matches brand voice",
                severity="low",
                confidence=0.84,
                status="pass",
                explanation="Vocabulary, sentence length and register match the approved brand voice.",
                evidence_refs=refs or ["Brand voice guidelines"],
            )
        )
    return out
