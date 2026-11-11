"""Sarvam pass over the legal registry.

The registry decides what a violation *is*; the model decides whether this
particular copy engages it, and explains it in plain words. Validation keeps the
model inside the registry: unknown codes, spans that are not in the copy, and
severity above the guideline's own ceiling are all rejected.
"""
from __future__ import annotations

from app.core.config import settings
from app.legal import guidelines as G
from app.schemas import FindingDraft
from app.services import sarvam

SYSTEM = (
    "You are the legal-content reviewer inside BrandSetGo, an Indian brand-governance platform. "
    "You are given a fixed list of guidelines with codes, obligations and fixes. "
    "Return ONLY JSON. Hard constraints:\n"
    "- Use only guideline codes from the supplied list. Never invent a code, an Act or a section.\n"
    "- The span must be an exact substring of the content.\n"
    "- Report only real, specific violations of the supplied guidelines. Do not report general style.\n"
    "- If the content is compliant, return an empty findings list. A false legal accusation is worse "
    "than a missed nuance.\n"
    "- Never use severity 'critical'; the deterministic pass owns the critical triggers.\n"
    "- Keep 'why' to two sentences and quote the obligation, do not paraphrase the law loosely."
)

SCHEMA = """{
  "findings": [
    {"guideline_code": "IN-...", "span": "exact substring", "severity": "low|medium|high",
     "confidence": 0.0, "why": "two sentences", "fix": "one concrete change"}
  ],
  "overall": "one sentence"
}"""


def _guideline_block(items: list[G.Guideline]) -> str:
    return "\n".join(
        f"- {g.code} | {g.title} | {g.authority} — {g.citation} | obligation: {g.obligation} | fix: {g.remediation}"
        for g in items
    )


async def scan(
    text: str,
    *,
    sector: str,
    channel: str,
    language: str,
    already_reported: list[str],
) -> tuple[list[FindingDraft], dict]:
    meta = {"called": False, "accepted": 0, "rejected": 0, "reasons": [], "latency_ms": 0, "error": None}
    if not (sarvam.enabled() and settings.ai_legal_review):
        return [], meta

    applicable = G.applicable(sector, channel)
    if not applicable:
        meta["error"] = "no-applicable-guidelines"
        return [], meta

    user = (
        f"GUIDELINES IN SCOPE ({G.REGISTRY_VERSION}):\n{_guideline_block(applicable)}\n\n"
        f"CONTEXT: sector={sector or 'unknown'}, channel={channel}, language={language}\n"
        f"ALREADY FLAGGED (do not repeat): {already_reported or 'none'}\n\n"
        f"SCHEMA:\n{SCHEMA}\n\n"
        f"CONTENT:\n<<<{text[:3500]}>>>"
    )
    result = await sarvam.chat_json(SYSTEM, user, max_tokens=1100)
    meta["called"] = True
    meta["latency_ms"] = result.latency_ms
    meta["tokens_in"] = result.tokens_in
    meta["tokens_out"] = result.tokens_out
    if not result.ok or not result.data:
        meta["error"] = result.error
        return [], meta

    by_code = {g.code: g for g in applicable}
    lowered = text.lower()
    out: list[FindingDraft] = []
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    for item in result.data.get("findings") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("guideline_code") or "")
        span = str(item.get("span") or "").strip()[:160]
        guideline = by_code.get(code)
        reason = None
        if guideline is None:
            reason = f"guideline '{code}' is not in scope for this brand"
        elif not span or span.lower() not in lowered:
            reason = "quote is not an exact substring of the copy"
        elif float(item.get("confidence") or 0) < 0.55:
            reason = "confidence below 0.55"
        if reason:
            meta["rejected"] += 1
            meta["reasons"].append(reason)
            continue

        severity = str(item.get("severity") or "medium").lower()
        if severity not in severity_order:
            severity = "medium"
        # never more severe than the guideline itself, never critical from the model
        if severity_order[severity] < severity_order[guideline.severity]:
            severity = guideline.severity
        if severity == "critical":
            severity = "high"

        why = str(item.get("why") or "").strip()[:600]
        fix = str(item.get("fix") or "").strip()[:400] or guideline.remediation

        out.append(
            FindingDraft(
                agent="legal",
                rule_code=guideline.code,
                title=guideline.title,
                severity=severity,  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, float(item.get("confidence") or 0.6))),
                status="needs_human_review",
                span_text=span,
                explanation=why or guideline.obligation,
                evidence_refs=[f"{guideline.authority} — {guideline.citation}"],
                source="sarvam",
                guideline_code=guideline.code,
                guideline_title=guideline.title,
                guideline_authority=guideline.authority,
                guideline_citation=guideline.citation,
                legal_basis=guideline.obligation,
                remediation=fix,
            )
        )
        meta["accepted"] += 1

    return out, meta
