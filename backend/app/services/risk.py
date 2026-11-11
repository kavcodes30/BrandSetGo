"""Brand Risk Score: transparent weighted factors, never a compliance verdict.

Missing checks produce "Incomplete", not a safe score. A critical rule blocks
approval regardless of the numeric result.
"""
from __future__ import annotations

SEVERITY_WEIGHT = {"critical": 100, "high": 32, "medium": 18, "low": 5}
SENSITIVITY_WEIGHT = {"public": 0, "internal": 2, "confidential": 7, "restricted": 13}
EXPECTED_AGENTS = ["tone", "facts", "claims", "visual", "accessibility", "legal"]


def band_for(score: int) -> str:
    if score < 25:
        return "low"
    if score < 55:
        return "medium"
    if score < 80:
        return "high"
    return "critical"


def compute(
    findings: list[dict],
    *,
    agents_expected: list[str],
    agents_returned: list[str],
    sensitivity: str,
    disagreement_count: int,
    asset_novel: bool,
    uncovered_categories: list[str],
) -> dict:
    blocking = [f for f in findings if f["status"] in ("confirmed", "needs_human_review")]
    severity_base = max((SEVERITY_WEIGHT.get(f["severity"], 0) for f in blocking), default=0)
    claim_sensitivity = 14 if any(f["agent"] == "claims" for f in blocking) else 3
    evidence_gaps = 8 * sum(1 for f in blocking if any("none found" in e for e in f.get("evidence_refs", [])))
    disagreement_penalty = 9 * disagreement_count
    novelty = 5 if asset_novel else 0
    coverage_penalty = 7 if uncovered_categories else 0
    sensitivity_penalty = SENSITIVITY_WEIGHT.get(sensitivity, 2)

    factors = [
        {"key": "severity", "label": "Confirmed violation severity", "points": severity_base,
         "note": f"Highest confirmed severity: {max((f['severity'] for f in blocking), default='none', key=lambda s: SEVERITY_WEIGHT.get(s, 0))}"},
        {"key": "claim_sensitivity", "label": "Claim sensitivity", "points": claim_sensitivity,
         "note": "Promotional or efficacy claims present" if claim_sensitivity > 3 else "No claim findings"},
        {"key": "evidence_gaps", "label": "Evidence gaps", "points": evidence_gaps,
         "note": "One or more findings have no supporting source" if evidence_gaps else "All findings cite a source"},
        {"key": "disagreements", "label": "Unresolved reviewer disagreement", "points": disagreement_penalty,
         "note": f"{disagreement_count} open disagreement(s)"},
        {"key": "asset_novelty", "label": "Asset novelty", "points": novelty,
         "note": "Unrecognised asset" if novelty else "Approved asset or text-only"},
        {"key": "policy_coverage", "label": "Policy coverage", "points": coverage_penalty,
         "note": f"No rule covers: {', '.join(uncovered_categories)}" if uncovered_categories else "Every category has an approved rule"},
        {"key": "sensitivity", "label": "Document sensitivity", "points": sensitivity_penalty,
         "note": f"Labelled {sensitivity}"},
    ]

    missing = [a for a in agents_expected if a not in agents_returned]
    completeness = {
        "expected": agents_expected,
        "returned": agents_returned,
        "missing": missing,
        "complete": not missing,
    }

    raw = sum(f["points"] for f in factors)
    score = min(100, int(round(raw)))
    hard_blocker = any(f["severity"] == "critical" and f["status"] == "confirmed" for f in findings)

    if missing:
        band = "incomplete"
    else:
        band = band_for(score)
        if hard_blocker:
            band = "critical"

    return {
        "score": score,
        "band": band,
        "factors": factors,
        "completeness": completeness,
        "hard_blocker": hard_blocker,
        "raw_total": raw,
    }
