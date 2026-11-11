"""Deterministic legal scan.

Pattern matching is the right tool here: a legal trigger either fires on the
words in the copy or it does not. The model is used afterwards, in `legal/ai.py`,
to catch implied violations and to explain them; it never invents a guideline.
"""
from __future__ import annotations

from app.legal import guidelines as G
from app.schemas import FindingDraft

MAX_SPAN = 160


def _explanation(g: G.Guideline, matched: str) -> str:
    return (
        f"\u201c{matched.strip()[:MAX_SPAN]}\u201d engages {g.title.lower()}. {g.obligation}"
    )


def scan(
    text: str,
    *,
    sector: str,
    channel: str,
    language: str = "en",
    only_codes: list[str] | None = None,
) -> list[FindingDraft]:
    """Return one finding per (guideline, matched span)."""
    if not text or not text.strip():
        return []

    lowered = text.lower()
    findings: list[FindingDraft] = []
    seen: set[tuple[str, str]] = set()

    for g in G.applicable(sector, channel):
        if only_codes and g.code not in only_codes:
            continue
        if g.requires_absent and any(marker in lowered for marker in g.requires_absent):
            continue

        for pattern in g.compiled():
            match = pattern.search(text)
            if not match:
                continue
            span = match.group(0).strip()[:MAX_SPAN]
            key = (g.code, span.lower())
            if key in seen:
                continue
            seen.add(key)

            findings.append(
                FindingDraft(
                    agent="legal",
                    rule_code=g.code,
                    title=g.title,
                    severity=g.severity,  # type: ignore[arg-type]
                    confidence=0.92,
                    status="confirmed",
                    span_text=span,
                    explanation=_explanation(g, span),
                    evidence_refs=[f"{g.authority} — {g.citation}"],
                    source="deterministic",
                    guideline_code=g.code,
                    guideline_title=g.title,
                    guideline_authority=g.authority,
                    guideline_citation=g.citation,
                    legal_basis=g.obligation,
                    remediation=g.remediation,
                )
            )
            # one finding per guideline is enough for a deterministic trigger
            break

    return findings
