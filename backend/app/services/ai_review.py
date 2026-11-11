"""Sarvam-backed semantic review, AI rewrites and rule extraction.

The deterministic checkers stay the source of evidence: they own the rule
matching, the product sheet comparison and the contrast maths. This layer adds
what pattern matching cannot see — implied promises, tone drift, a missing
disclaimer, cultural sensitivity — and phrases the explanation in plain words.

Everything the model returns is validated before it can become a finding:
* the agent must be a real checker;
* the rule code must be one of the rules retrieved for this brand and channel;
* the quoted span must be an exact substring of the copy;
* the evidence attached is the rule's own source, never the model's claim of one.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models import ApprovedClaim, BrandRule, GlossaryTerm
from app.schemas import FindingDraft, RuleDraft, SuggestedPatch
from app.services import sarvam
from app.services.agents.claims import ABSOLUTE, DURATION, EFFICACY, PROOF, THERAPEUTIC

AGENTS = {"tone", "facts", "claims", "visual", "accessibility", "language"}
SEVERITIES = {"low", "medium", "high", "critical"}
STATUSES = {"confirmed", "needs_human_review", "inconclusive"}
PROMISE_PATTERNS = (DURATION, PROOF, THERAPEUTIC, EFFICACY, ABSOLUTE)
NUMBER = re.compile(r"\d")

SYSTEM = (
    "You are the semantic reviewer inside BrandSetGo, an Indian brand-governance platform. "
    "You review brand content against a supplied rule set. Return ONLY JSON.\n"
    "Hard constraints:\n"
    "- Never invent a rule code, a source document or a quote. The span must be an exact substring.\n"
    "- Only review these three things: (1) an implied or explicit performance/health/duration/"
    "guarantee promise that the approved claims do not cover, (2) brand-voice or restricted-language "
    "drift, (3) a translation or glossary problem in a non-English variant.\n"
    "- Facts, prices, sizes, logos, contrast and alt text are checked elsewhere. Never file a finding "
    "about them. A discount or price offer is NOT a substantiation problem.\n"
    "- Do not file a finding about a phrase that appears in the approved claims list.\n"
    "- Do not repeat anything already reported.\n"
    "- Severity: use medium for style, high only for a real unsupported promise. Never use critical.\n"
    "- If unsure, return no finding. A false accusation costs a creator more than a missed nuance."
)

REVIEW_SCHEMA = """{
  "findings": [
    {
      "agent": "tone|facts|claims|visual|accessibility|language",
      "rule_code": "one of the supplied rule codes",
      "span": "exact substring of the content",
      "title": "max 8 words",
      "severity": "low|medium|high|critical",
      "confidence": 0.0,
      "status": "confirmed|needs_human_review|inconclusive",
      "explanation": "1-2 plain sentences a non-lawyer understands",
      "suggested_replacement": "minimal replacement for the span, or empty string"
    }
  ],
  "overall": "one sentence summary"
}"""


# A claims finding must quote actual promise language; this keeps the model out of
# ordinary marketing copy ("20% off", "a deep oud trail") that is not a claim.
PROMISE_CUES = (
    "lasts", "lasting", "proven", "clinical", "dermatolog", "cure", "treat", "heal",
    "guarantee", "100%", "instant", "overnight", "removes", "eliminates", "reduces",
    "prevents", "kills", "restores", "reverses", "best in", "no.1", "number one",
    "safe for", "chemical-free", "fda", "certified",
)
AI_ALLOWED_AGENTS = {"claims", "tone", "language"}
AI_SEVERITY_CAP = {"claims": "high", "tone": "medium", "language": "high"}


class AIFinding(BaseModel):
    agent: str
    rule_code: str = ""
    span: str = ""
    title: str = ""
    severity: str = "medium"
    confidence: float = 0.6
    status: str = "needs_human_review"
    explanation: str = ""
    suggested_replacement: str = ""


class AIReviewPayload(BaseModel):
    findings: list[AIFinding] = Field(default_factory=list)
    overall: str = ""


def _rules_block(rules: list[BrandRule]) -> str:
    return "\n".join(
        f"- {r.code} | {r.category} | severity {r.severity} | {r.title}: {r.statement}"
        for r in rules
    )


def _claims_block(claims: list[ApprovedClaim]) -> str:
    if not claims:
        return "none on file"
    return "\n".join(f"- \"{c.text}\" (source: {c.evidence_ref or 'approved registry'})" for c in claims)


def _glossary_block(glossary: list[GlossaryTerm]) -> str:
    if not glossary:
        return "none"
    return "\n".join(
        f"- {g.term_en}: hi=\"{g.term_hi}\" mr=\"{g.term_mr}\" never use {g.prohibited or '[]'}"
        for g in glossary
    )


async def semantic_findings(
    *,
    content: str,
    language: str,
    channel: str,
    audience: str,
    rules: list[BrandRule],
    claims: list[ApprovedClaim],
    glossary: list[GlossaryTerm],
    already_reported: list[str],
    classified_claims: list[dict] | None = None,
) -> tuple[list[FindingDraft], dict]:
    """One batched Sarvam call for all six checkers."""
    meta = {
        "called": False,
        "accepted": 0,
        "rejected": 0,
        "reasons": [],
        "latency_ms": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "error": None,
    }
    if not (sarvam.enabled() and settings.ai_semantic_review):
        return [], meta
    if not rules:
        meta["error"] = "no-policy"
        return [], meta

    body = content[:3500]
    user = (
        f"RULES IN FORCE:\n{_rules_block(rules)}\n\n"
        f"APPROVED CLAIMS (the only substantiation that exists):\n{_claims_block(claims)}\n\n"
        f"BRAND GLOSSARY:\n{_glossary_block(glossary)}\n\n"
        f"CONTEXT: channel={channel}, language={language}, audience={audience or 'unspecified'}\n"
        f"ALREADY REPORTED (do not repeat): {already_reported or 'none'}\n\n"
        f"CLASSIFIER TAGGED THESE AS CLAIMS: "
        f"{[c.get('text') for c in (classified_claims or [])] or 'none'}\n\n"
        f"SCHEMA:\n{REVIEW_SCHEMA}\n\n"
        f"CONTENT:\n<<<{body}>>>"
    )
    result = await sarvam.chat_json(SYSTEM, user, max_tokens=1200)
    meta["called"] = True
    meta["latency_ms"] = result.latency_ms
    meta["tokens_in"] = result.tokens_in
    meta["tokens_out"] = result.tokens_out
    if not result.ok or not result.data:
        meta["error"] = result.error
        return [], meta

    payload = AIReviewPayload(**{k: v for k, v in result.data.items() if k in ("findings", "overall")})
    rule_map = {r.code: r for r in rules}
    lowered = body.lower()
    out: list[FindingDraft] = []

    for f in payload.findings:
        if f.agent not in AGENTS:
            meta["rejected"] += 1
            meta["reasons"].append(f"unknown agent '{f.agent}'")
            continue
        if f.rule_code not in rule_map:
            meta["rejected"] += 1
            meta["reasons"].append(f"rule '{f.rule_code}' is not in force for this brand")
            continue

        rule = rule_map[f.rule_code]
        reason = verify_ai_finding(
            f,
            rule=rule,
            content=body,
            language=language,
            claims=claims,
            glossary=glossary,
            classified_claims=classified_claims,
        )
        if reason:
            meta["rejected"] += 1
            meta["reasons"].append(reason)
            continue

        status = f.status if f.status in STATUSES else "needs_human_review"
        severity = clamp_severity(f.severity, rule.severity, f.agent)

        replacement = (f.suggested_replacement or "").strip()
        patch = None
        if replacement and f.span and _rewrite_is_safe(f.span, replacement, body):
            patch = SuggestedPatch(
                replacement=replacement,
                reason=f"Semantic reviewer: {rule.title.lower()}.",
                rule_code=rule.code,
            )

        out.append(
            FindingDraft(
                agent=f.agent,  # type: ignore[arg-type]
                rule_code=rule.code,
                title=(f.title or rule.title)[:120],
                severity=severity,  # type: ignore[arg-type]
                confidence=max(0.0, min(1.0, f.confidence)),
                status=status,  # type: ignore[arg-type]
                span_text=f.span[:400],
                explanation=(f.explanation or rule.statement)[:800],
                evidence_refs=[rule.evidence_ref or rule.source_ref or "Brand policy"],
                suggested_patch=patch,
                source="sarvam",
            )
        )
        meta["accepted"] += 1

    return out, meta


SEVERITIES_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def clamp_severity(model_severity: str, rule_severity: str, agent: str) -> str:
    """Never more severe than the agent's cap, never softer than the rule it cites."""
    order = SEVERITIES_ORDER  # lower number = more severe
    cap = AI_SEVERITY_CAP.get(agent, "high")
    severity = model_severity if model_severity in SEVERITIES else rule_severity
    if order[severity] < order[cap]:
        severity = cap
    if order[severity] > order.get(rule_severity, 2):
        severity = rule_severity
    if order[severity] < order[cap]:
        severity = cap
    return severity


# Claim types the classifier can vouch for. Facts (price, size, ingredient)
# stay with the deterministic sheet comparison.
CLASSIFIED_CLAIM_TYPES = {"duration", "efficacy", "clinical", "absolute"}


def _classified_claim_cover(span: str, classified_claims: list[dict]) -> str:
    """Return the claim type when the classifier independently tagged this span."""
    lowered = span.lower()
    for claim in classified_claims or []:
        text = str(claim.get("text") or "").lower()
        if not text or claim.get("type") not in CLASSIFIED_CLAIM_TYPES:
            continue
        if text in lowered or lowered in text:
            return str(claim.get("type"))
    return ""


def verify_ai_finding(
    f: AIFinding,
    *,
    rule: BrandRule,
    content: str,
    language: str,
    claims: list[ApprovedClaim],
    glossary: list[GlossaryTerm],
    classified_claims: list[dict] | None = None,
) -> str | None:
    """Return a rejection reason, or None when the finding survives.

    This is the layer that stops a plausible-sounding model answer from
    becoming an accusation: ownership of facts stays deterministic, an
    approved claim cannot be re-accused, and critical severity is never
    issued by the model.
    """
    from app.services.agents.base import is_supported

    if f.agent not in AI_ALLOWED_AGENTS:
        return f"agent '{f.agent}' is deterministic-only"
    if f.agent != rule.category:
        return f"agent '{f.agent}' cannot cite a '{rule.category}' rule"
    if f.span and f.span.lower() not in content.lower():
        return "quote is not an exact substring of the copy"
    if f.status == "confirmed" and not f.span:
        return "a confirmed finding must point at a span"
    if f.confidence < 0.55:
        return "confidence below 0.55"

    if f.agent == "claims":
        if is_supported(f.span, claims)[0]:
            return "the phrase is an approved claim with a source on file"
        lowered = f.span.lower()
        # a literal promise cue, or an independent classification of this exact
        # span as a duration/efficacy/clinical/absolute claim
        if not any(cue in lowered for cue in PROMISE_CUES) and not _classified_claim_cover(
            f.span, classified_claims or []
        ):
            return "no promise language in the quote and no claim classification for it"
    if f.agent == "language":
        if language == "en":
            return "translation findings do not apply to English source copy"
        prohibited = [bad for g in glossary for bad in (g.prohibited or [])]
        approved_terms = [t for g in glossary for t in (g.term_hi, g.term_mr) if t]
        if not any(p in f.span for p in prohibited) and not any(t in f.span for t in approved_terms):
            return "no glossary term or prohibited translation in the quote"
    if f.agent == "tone" and rule.category != "tone":
        return "tone finding must cite a tone rule"
    return None


def _rewrite_is_safe(original: str, replacement: str, content: str) -> bool:
    """A model rewrite may not introduce numbers or new promises."""
    if len(replacement) > max(60, len(original) * 4):
        return False
    if set(NUMBER.findall(replacement)) - set(NUMBER.findall(original)):
        return False
    new_promises = {m.group(0).lower() for p in PROMISE_PATTERNS for m in p.finditer(replacement)}
    old_promises = {m.group(0).lower() for p in PROMISE_PATTERNS for m in p.finditer(original)}
    return new_promises.issubset(old_promises)


async def suggest_rewrite(
    *, span: str, content: str, rule: BrandRule | None, language: str
) -> tuple[str | None, dict]:
    """Ask Sarvam for a minimal replacement of one span, then police it."""
    meta = {"called": False, "accepted": False, "latency_ms": 0, "error": None}
    if not (sarvam.enabled() and settings.ai_rewrite):
        return None, meta

    rule_line = f"Rule: {rule.code} — {rule.statement}" if rule else "Rule: brand policy"
    user = (
        f"{rule_line}\nLanguage: {language}\n"
        "Rewrite ONLY the quoted span so it satisfies the rule while keeping the same message, "
        "the same call to action, the same audience and the same facts. Do not add numbers, "
        "do not add promises, do not add sentences.\n"
        f'Return JSON: {{"replacement": "..."}}\n\n'
        f"FULL COPY: <<<{content[:2500]}>>>\n\nSPAN TO REPLACE: <<<{span}>>>"
    )
    result = await sarvam.chat_json(SYSTEM, user, max_tokens=250)
    meta["called"] = True
    meta["latency_ms"] = result.latency_ms
    if not result.ok or not result.data:
        meta["error"] = result.error
        return None, meta
    replacement = str(result.data.get("replacement") or "").strip()
    if not replacement or not _rewrite_is_safe(span, replacement, content):
        meta["error"] = "rejected-by-guard"
        return None, meta
    meta["accepted"] = True
    return replacement[:300], meta


RULE_SCHEMA = """{
  "rules": [
    {"code": "R-01", "title": "max 8 words", "category": "tone|facts|claims|visual|accessibility|language",
     "statement": "one enforceable sentence", "severity": "low|medium|high|critical",
     "evidence_ref": "which part of the guidelines this came from"}
  ]
}"""


async def extract_rules(guideline_text: str, *, brand_name: str, sector: str, channels: list[str]) -> tuple[list[RuleDraft], dict]:
    """Turn pasted brand guidelines into draft rules for a human to approve."""
    meta = {"called": False, "accepted": 0, "latency_ms": 0, "error": None}
    if not (sarvam.enabled() and settings.ai_rule_extraction):
        return [], meta

    user = (
        f"Brand: {brand_name} (sector: {sector or 'unknown'}). Channels: {', '.join(channels) or 'all'}.\n"
        "Extract enforceable review rules from these brand guidelines. Only rules a reviewer could "
        "check mechanically against a piece of content. No advice, no slogans.\n"
        f"SCHEMA:\n{RULE_SCHEMA}\n\nGUIDELINES:\n<<<{guideline_text[:6000]}>>>"
    )
    result = await sarvam.chat_json(SYSTEM, user, max_tokens=1200)
    meta["called"] = True
    meta["latency_ms"] = result.latency_ms
    if not result.ok or not result.data:
        meta["error"] = result.error
        return [], meta

    drafts: list[RuleDraft] = []
    for i, item in enumerate(result.data.get("rules") or [], start=1):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").lower()
        if category not in {"tone", "facts", "claims", "visual", "accessibility", "language"}:
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in SEVERITIES:
            severity = "medium"
        drafts.append(
            RuleDraft(
                code=str(item.get("code") or f"R-{i:02d}")[:12],
                title=str(item.get("title") or "Extracted rule")[:200],
                category=category,  # type: ignore[arg-type]
                statement=str(item.get("statement") or "")[:600],
                severity=severity,  # type: ignore[arg-type]
                scope=channels,
                source_ref="Brand guidelines (extracted)",
                evidence_ref=str(item.get("evidence_ref") or "Brand guidelines")[:240],
            )
        )
    meta["accepted"] = len(drafts)
    return drafts, meta
