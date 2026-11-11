"""Shared context and text helpers for the independent checkers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import ApprovedClaim, Asset, Brand, BrandRule, GlossaryTerm, Product

WORD = re.compile(r"[a-z0-9']+", re.I)


@dataclass
class AgentContext:
    brand: Brand
    content: str
    channel: str
    language: str
    sensitivity: str
    meta: dict = field(default_factory=dict)
    rules: list[BrandRule] = field(default_factory=list)
    claims: list[ApprovedClaim] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    assets: list[Asset] = field(default_factory=list)
    glossary: list[GlossaryTerm] = field(default_factory=list)
    approved_examples: list[str] = field(default_factory=list)

    def rule(self, category: str) -> BrandRule | None:
        """Most severe authoritative rule for a category in scope for this channel."""
        candidates = [
            r
            for r in self.rules
            if r.category == category and (not r.scope or self.channel in r.scope)
        ]
        if not candidates:
            candidates = [r for r in self.rules if r.category == category]
        if not candidates:
            return None
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(candidates, key=lambda r: order.get(r.severity, 4))[0]

    def rule_ref(self, category: str) -> list[str]:
        r = self.rule(category)
        if not r:
            return []
        return [f"{r.code} · {r.title}", r.evidence_ref or r.source_ref or "Brand policy"]

    def product_mentioned(self) -> Product | None:
        if not self.products:
            return None
        tokens = set(WORD.findall(self.content.lower()))
        best, best_score = None, 0.0
        for p in self.products:
            ptokens = set(WORD.findall(p.name.lower()))
            if not ptokens:
                continue
            score = len(tokens & ptokens) / len(ptokens)
            if score > best_score:
                best, best_score = p, score
        return best if best_score >= 0.5 else (self.products[0] if len(self.products) == 1 else None)


def overlap(a: str, b: str) -> float:
    """Token overlap used for claim matching and drift similarity."""
    ta, tb = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_supported(span: str, claims: list[ApprovedClaim]) -> tuple[bool, str]:
    for c in claims:
        if c.status != "verified":
            continue
        if c.expires_at is not None and c.expires_at.year < 2000:
            continue
        if overlap(span, c.text) >= 0.5 or span.lower() in c.text.lower():
            return True, c.evidence_ref or "Approved claims registry"
    return False, ""


def contrast_ratio(fg: str, bg: str) -> float | None:
    """WCAG 2.1 relative-luminance contrast, deterministic."""
    def lum(hexcode: str) -> float:
        h = hexcode.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        try:
            r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
        except (ValueError, IndexError):
            raise ValueError(hexcode)
        def chan(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)

    try:
        l1, l2 = lum(fg), lum(bg)
    except ValueError:
        return None
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)
