"""Legal / Claims checker: unsupported promises and regulatory triggers."""
from __future__ import annotations

import re

from app.schemas import FindingDraft, SuggestedPatch
from app.services.agents.base import AgentContext, is_supported

DURATION = re.compile(
    r"\b(?:lasts?|stays?|lingers?|works?)\s+(?:for\s+)?(?:\d+\s*(?:hours?|hrs?|days?)|all\s+day|the\s+whole\s+day|24\s*hours?)\b",
    re.I,
)
PROOF = re.compile(
    r"\b(?:clinically|dermatologically|scientifically|lab[- ]tested)\s+(?:proven|tested)\b[^.,!?;]*",
    re.I,
)
ABSOLUTE = re.compile(
    r"\b(?:100\s*%|guaranteed|no\.?\s*1|number\s+one|best\s+in\s+the\s+world|instantly|overnight)\b", re.I
)
THERAPEUTIC = re.compile(r"\b(?:cures?|treats?|heals?|kills?\s+bacteria|prevents?\s+infection)\b", re.I)
EFFICACY = re.compile(
    r"\b(?:removes?\s+wrinkles?|eliminates?\s+wrinkles?|anti-?ageing\s+treatment|reverses?\s+ageing)\b", re.I
)

PROOF_REPLACEMENT = {
    "skin": "helps skin look smoother with daily use",
    "serum": "helps skin look smoother with daily use",
    "cream": "helps skin look smoother with daily use",
    "default": "made with carefully selected ingredients",
}


def _rule_for(ctx: AgentContext, kind: str):
    """Cite the rule that actually governs this kind of claim."""
    rules = [r for r in ctx.rules if r.category == "claims"] or [ctx.rule("claims")]
    rules = [r for r in rules if r is not None]
    if not rules:
        return None
    if kind == "therapeutic":
        for r in rules:
            if "therapeutic" in r.title.lower() or "cure" in r.statement.lower():
                return r
    else:
        for r in rules:
            if "substantiat" in r.title.lower() or "substantiat" in r.statement.lower():
                return r
    order = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    return sorted(rules, key=lambda r: order.get(r.severity, 0))[0]


def _soften(span: str, content: str) -> str:
    for key, repl in PROOF_REPLACEMENT.items():
        if key != "default" and key in content.lower():
            return repl
    return PROOF_REPLACEMENT["default"]


def run(ctx: AgentContext) -> list[FindingDraft]:
    refs = ctx.rule_ref("claims")
    out: list[FindingDraft] = []
    text = ctx.content
    taken: list[tuple[int, int]] = []

    patterns = (
        # most specific and most severe first: a cure claim inside "clinically proven to cure X"
        # must be reported as a therapeutic claim, not as a proof-claim wrapper
        (THERAPEUTIC, "therapeutic", "critical"),
        (PROOF, "proof", "high"),
        (DURATION, "duration", "high"),
        (EFFICACY, "efficacy", "high"),
        (ABSOLUTE, "absolute", "medium"),
    )

    for pattern, kind, severity in patterns:
        for m in pattern.finditer(text):
            start, end = m.span()
            # a narrower pattern inside an already-reported span adds no information
            if any(s <= start and end <= e for s, e in taken):
                continue
            span = m.group(0).strip()
            rule = _rule_for(ctx, kind)
            code = rule.code if rule else "R-CLAIMS"
            supported, evidence = is_supported(span, ctx.claims)
            if supported:
                out.append(
                    FindingDraft(
                        agent="claims",
                        rule_code=code,
                        title=f"Supported {kind} claim",
                        severity="low",
                        confidence=0.86,
                        status="pass",
                        span_text=span,
                        explanation=f"Claim is backed by an approved source: {evidence}.",
                        evidence_refs=[evidence],
                    )
                )
                taken.append((start, end))
                continue

            if kind == "duration":
                replacement = "long-lasting"
                reason = "Duration is unverified; a qualitative descriptor carries the same benefit without a testable promise."
            elif kind in ("proof", "efficacy", "therapeutic"):
                replacement = _soften(span, text)
                reason = "No approved substantiation on file for a clinical or therapeutic promise; rephrased as a descriptive benefit."
            else:
                replacement = ""
                reason = "Absolute guarantee removed: no evidence on file and guarantees trigger regulatory review."

            out.append(
                FindingDraft(
                    agent="claims",
                    rule_code=code,
                    title={
                        "duration": "Unsupported duration claim",
                        "proof": "Unsupported efficacy claim",
                        "efficacy": "Unsupported efficacy claim",
                        "therapeutic": "Therapeutic claim on a cosmetic product",
                        "absolute": "Absolute / guarantee claim",
                    }[kind],
                    severity=severity,
                    confidence=0.9 if kind != "absolute" else 0.78,
                    status="confirmed" if kind != "absolute" else "needs_human_review",
                    span_text=span,
                    explanation=(
                        f"\u201c{span}\u201d has no support in your approved sources. "
                        f"{'Therapeutic claims are not permitted for cosmetic products.' if kind == 'therapeutic' else 'Add substantiation or qualify the wording.'}"
                    ),
                    evidence_refs=["Evidence: none found"] + refs[:1],
                    suggested_patch=SuggestedPatch(replacement=replacement, reason=reason, rule_code=code),
                )
            )
            taken.append((start, end))
    return out
