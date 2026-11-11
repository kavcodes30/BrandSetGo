"""Trust-based approval routing.

Trust changes the path, never the outcome: critical findings always escalate
and an incomplete review can never auto-clear.
"""
from __future__ import annotations


def decide(
    *,
    score: int,
    band: str,
    hard_blocker: bool,
    completeness: dict,
    disagreement_count: int,
    evidence_gaps: int,
    trust_score: float,
    sector: str,
    fast_track_max: int,
    manager_max: int,
    trust_floor: float,
    auto_clear_enabled: bool,
) -> dict:
    regulated = sector.lower() in {"health", "healthcare", "finance", "insurance", "pharma", "alcohol", "tobacco"}

    if hard_blocker or regulated:
        return {
            "route": "legal",
            "approver_role": "legal",
            "reason": (
                "A critical claim finding blocks approval until an authorised legal reviewer decides."
                if hard_blocker
                else "Sector is regulated, so a legal/compliance reviewer is required."
            ),
            "auto_clear": False,
        }
    if not completeness.get("complete", False):
        return {
            "route": "specialist",
            "approver_role": "specialist",
            "reason": f"Checks incomplete ({', '.join(completeness.get('missing', []))}); a review cannot be treated as safe.",
            "auto_clear": False,
        }
    if disagreement_count or evidence_gaps:
        return {
            "route": "specialist",
            "approver_role": "specialist",
            "reason": "Reviewers disagree or evidence is missing, so a specialist decides.",
            "auto_clear": False,
        }
    if score <= fast_track_max and trust_score >= trust_floor:
        return {
            "route": "fast_track",
            "approver_role": "owner",
            "reason": f"Low risk ({score}/100) with a trusted creator (trust {trust_score:.2f}).",
            "auto_clear": bool(auto_clear_enabled),
        }
    if score <= manager_max:
        return {
            "route": "manager",
            "approver_role": "manager",
            "reason": f"Medium risk ({score}/100) needs brand manager approval before publishing.",
            "auto_clear": False,
        }
    return {
        "route": "manager",
        "approver_role": "manager",
        "reason": f"High risk ({score}/100) with no legal trigger; brand manager decision required.",
        "auto_clear": False,
    }
