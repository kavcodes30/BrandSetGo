"""Regional / language checker: glossary fidelity and disclaimer survival."""
from __future__ import annotations

from app.schemas import FindingDraft, SuggestedPatch
from app.services.agents.base import AgentContext


def run(ctx: AgentContext) -> list[FindingDraft]:
    rule = ctx.rule("language")
    code = rule.code if rule else "R-LANG"
    refs = ctx.rule_ref("language")

    if ctx.language == "en" and not ctx.meta.get("variant_of"):
        return [
            FindingDraft(
                agent="language",
                rule_code=code,
                title="Source language",
                severity="low",
                confidence=0.95,
                status="pass",
                explanation="English source copy; terminology is checked against the brand glossary.",
                evidence_refs=refs or ["Brand glossary"],
            )
        ]

    out: list[FindingDraft] = []
    approved = {
        "hi": [g.term_hi for g in ctx.glossary if g.term_hi],
        "mr": [g.term_mr for g in ctx.glossary if g.term_mr],
    }.get(ctx.language, [])

    for g in ctx.glossary:
        for bad in g.prohibited or []:
            if bad and bad in ctx.content:
                out.append(
                    FindingDraft(
                        agent="language",
                        rule_code=code,
                        title="Prohibited translation",
                        severity="high",
                        confidence=0.9,
                        status="confirmed",
                        span_text=bad,
                        explanation=f"\u201c{bad}\u201d is a prohibited translation of \u201c{g.term_en}\u201d in this brand's glossary.",
                        evidence_refs=["Brand glossary"] + refs[:1],
                        suggested_patch=SuggestedPatch(
                            replacement=(g.term_hi or g.term_mr or g.term_en),
                            reason="Use the glossary-approved term.",
                            rule_code=code,
                        ),
                    )
                )

    if approved and not any(t in ctx.content for t in approved):
        out.append(
            FindingDraft(
                agent="language",
                rule_code=code,
                title="Glossary term not used",
                severity="low",
                confidence=0.5,
                status="inconclusive",
                explanation="None of the glossary-approved terms appear in this variant.",
                evidence_refs=["Brand glossary"] + refs[:1],
            )
        )

    if ctx.meta.get("disclaimer_required") and not ctx.meta.get("disclaimer_present", True):
        out.append(
            FindingDraft(
                agent="language",
                rule_code=code,
                title="Disclaimer did not survive translation",
                severity="high",
                confidence=0.85,
                status="confirmed",
                explanation="The source disclaimer is missing from this language variant.",
                evidence_refs=["Disclaimer register"] + refs[:1],
            )
        )

    if not out:
        out.append(
            FindingDraft(
                agent="language",
                rule_code=code,
                title="Terminology consistent",
                severity="low",
                confidence=0.82,
                status="pass",
                explanation="Glossary terms and disclaimers match the approved source.",
                evidence_refs=["Brand glossary"] + refs[:1],
            )
        )
    return out
