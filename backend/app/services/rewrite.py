"""Minimal, reversible patch generation.

A correction is a patch, never a rewrite: offsets, original span, replacement,
reason and the rule that justified it. There is deliberately no "accept all".
"""
from __future__ import annotations

from app.schemas import FindingDraft


def build_patches(content: str, findings: list[FindingDraft]) -> list[dict]:
    patches: list[dict] = []
    used: list[tuple[int, int]] = []
    for f in findings:
        patch = f.suggested_patch
        if not patch or not f.span_text:
            continue
        start = content.find(f.span_text)
        if start < 0:
            continue
        end = start + len(f.span_text)
        if any(s < end and start < e for s, e in used):
            continue
        used.append((start, end))
        patches.append(
            {
                "start": start,
                "end": end,
                "original": f.span_text,
                "replacement": patch.replacement,
                "reason": patch.reason,
                "rule_code": patch.rule_code or f.rule_code,
                "evidence_refs": f.evidence_refs,
            }
        )
    return patches


def apply_patches(content: str, decisions: list[dict]) -> str:
    """Apply accepted/edited patches right-to-left so offsets stay valid."""
    accepted = [d for d in decisions if d["decision"] in ("accepted", "edited")]
    out = content
    for p in sorted(accepted, key=lambda x: x["start"], reverse=True):
        replacement = p.get("edited_text") or p["replacement"]
        out = out[: p["start"]] + replacement + out[p["end"] :]
    return out
