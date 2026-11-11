"""Meaning-drift verification.

Semantic similarity is a warning signal, never proof. The structured validator
checks explicit invariants; if any invariant fails, automatic acceptance is
blocked and the creator must revise.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.services.agents.claims import ABSOLUTE, DURATION, EFFICACY, PROOF, THERAPEUTIC

NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ml|g|kg|%|hours?|days?)?\b", re.I)
DEMOGRAPHIC = re.compile(r"\b(?:men|women|kids|children|teens|adults|seniors|students|professionals)\b", re.I)
QUALIFIER = re.compile(r"\b(?:helps?|may|might|can|up\s+to|designed\s+to|supports?)\b", re.I)
PROMISE_PATTERNS = (DURATION, PROOF, THERAPEUTIC, EFFICACY, ABSOLUTE)


def similarity(a: str, b: str) -> float:
    return round(SequenceMatcher(None, a.lower().split(), b.lower().split()).ratio(), 3)


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def invariants(
    original: str,
    revised: str,
    *,
    desired_cta: str = "",
    audience: str = "",
    edited_spans: list[tuple[int, int]] | None = None,
) -> list[dict]:
    """Invariants are checked outside the spans the creator actually edited.

    A duration the creator deliberately removed is not "fact drift"; a quantity
    that changed somewhere else is.
    """
    edited = edited_spans or []
    checks: list[dict] = []

    # only enforce the CTA when the original copy actually carried it: a declared
    # CTA is often a button label, not part of the body text
    cta_in_original = bool(desired_cta) and desired_cta.lower() in original.lower()
    cta_ok = (not cta_in_original) or (desired_cta.lower() in revised.lower())
    checks.append(
        {
            "key": "cta_preserved",
            "label": "Call to action preserved",
            "passed": cta_ok,
            "detail": (
                "No CTA in the original copy, so nothing to preserve"
                if not cta_in_original
                else (f"CTA \u201c{desired_cta}\u201d still present" if cta_ok else f"CTA \u201c{desired_cta}\u201d was lost")
            ),
        }
    )

    orig_demo = set(w.lower() for w in DEMOGRAPHIC.findall(original))
    new_demo = set(w.lower() for w in DEMOGRAPHIC.findall(revised))
    audience_ok = orig_demo == new_demo
    checks.append(
        {
            "key": "audience_preserved",
            "label": "Audience unchanged",
            "passed": audience_ok,
            "detail": (audience or "Target audience") + (" unchanged" if audience_ok else " was altered"),
        }
    )

    orig_nums = {
        m.group(0).lower().replace(" ", "")
        for m in NUMBER.finditer(original)
        if not _in_spans(m.start(), edited)
    }
    new_nums = set(n.lower().replace(" ", "") for n in NUMBER.findall(revised))
    facts_ok = orig_nums == new_nums
    checks.append(
        {
            "key": "key_facts_unchanged",
            "label": "Key facts and quantities unchanged",
            "passed": facts_ok,
            "detail": "All quantities, sizes and prices retained" if facts_ok else "A quantity or number changed",
        }
    )

    disclaimer_re = re.compile(r"(\*[^.]{4,}|terms and conditions[^.]*)", re.I)
    orig_disc = set(disclaimer_re.findall(original))
    new_disc = set(disclaimer_re.findall(revised))
    disc_ok = orig_disc.issubset(new_disc)
    checks.append(
        {
            "key": "disclaimers_unchanged",
            "label": "Disclaimers retained",
            "passed": disc_ok,
            "detail": "Disclaimers intact" if disc_ok else "A disclaimer was dropped",
        }
    )

    orig_promises = {m.group(0).lower() for p in PROMISE_PATTERNS for m in p.finditer(original)}
    new_promises = {m.group(0).lower() for p in PROMISE_PATTERNS for m in p.finditer(revised)}
    added = new_promises - orig_promises
    checks.append(
        {
            "key": "no_new_promises",
            "label": "No new promises introduced",
            "passed": not added,
            "detail": "No new claims" if not added else f"New promise added: {', '.join(sorted(added)[:2])}",
        }
    )

    orig_qual = set(w.lower() for w in QUALIFIER.findall(original))
    new_qual = set(w.lower() for w in QUALIFIER.findall(revised))
    qual_ok = orig_qual.issubset(new_qual)
    checks.append(
        {
            "key": "qualifiers_preserved",
            "label": "Qualifiers kept",
            "passed": qual_ok,
            "detail": "Hedging language kept" if qual_ok else "A qualifier was removed, strengthening the claim",
        }
    )
    return checks


def evaluate(
    original: str,
    revised: str,
    *,
    desired_cta: str = "",
    audience: str = "",
    edited_spans: list[tuple[int, int]] | None = None,
) -> dict:
    checks = invariants(
        original, revised, desired_cta=desired_cta, audience=audience, edited_spans=edited_spans
    )
    sim = similarity(original, revised)
    failed = [c for c in checks if not c["passed"]]
    return {
        "similarity": sim,
        "invariants": checks,
        "passed": not failed,
        "blocking_reason": "" if not failed else "; ".join(c["detail"] for c in failed),
        "warning": (
            "Semantic similarity is low; confirm the message still reads as intended."
            if sim < 0.5
            else ""
        ),
    }
