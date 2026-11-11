"""Reconciliation node: deduplicate findings, preserve contradictions."""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas import FindingDraft
from app.services.agents.base import overlap


@dataclass
class Disagreement:
    topic: str
    span_text: str
    agent_a: str
    agent_a_status: str
    agent_b: str
    agent_b_status: str
    summary: str


def dedupe(findings: list[FindingDraft]) -> list[FindingDraft]:
    seen: dict[tuple, FindingDraft] = {}
    for f in findings:
        key = (f.agent, f.rule_code, f.span_text.lower().strip(), f.status)
        if key in seen:
            if f.confidence > seen[key].confidence:
                seen[key] = f
            continue
        seen[key] = f
    return list(seen.values())


def find_disagreements(findings: list[FindingDraft]) -> list[Disagreement]:
    """A pass and a blocking finding on the same span are a real disagreement.

    The system never silently votes a critical concern away: both opinions are
    returned so a human can resolve them.
    """
    out: list[Disagreement] = []
    blocking = [f for f in findings if f.status in ("confirmed", "needs_human_review") and f.span_text]
    passing = [f for f in findings if f.status == "pass" and f.span_text]

    for b in blocking:
        for p in passing:
            if p.agent == b.agent:
                continue
            same = p.span_text.lower().strip() == b.span_text.lower().strip()
            if not same and overlap(p.span_text, b.span_text) < 0.6:
                continue
            out.append(
                Disagreement(
                    topic=f"{p.agent.title()} and {b.agent.title()} disagree",
                    span_text=b.span_text,
                    agent_a=p.agent,
                    agent_a_status="approved",
                    agent_b=b.agent,
                    agent_b_status="blocked",
                    summary=(
                        f"{p.agent.title()} approves \u201c{p.span_text}\u201d; "
                        f"{b.agent.title()} cannot verify it. A human decides."
                    ),
                )
            )
    # one card per span is enough for the panel
    unique: dict[str, Disagreement] = {}
    for d in out:
        unique.setdefault(d.span_text.lower(), d)
    return list(unique.values())
