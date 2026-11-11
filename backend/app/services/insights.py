"""Brand intelligence: governance analytics from real review history."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AgentDisagreement,
    AgentFinding,
    Brand,
    BrandRule,
    Clearance,
    ContentItem,
    ContentVersion,
    ReviewRun,
    RoutingDecision,
)


def brand_insights(db: Session, brand_id: str) -> dict:
    runs = list(db.scalars(select(ReviewRun).where(ReviewRun.brand_id == brand_id)))
    run_ids = [r.id for r in runs]
    findings: list[AgentFinding] = []
    disagreements: list[AgentDisagreement] = []
    routes: list[RoutingDecision] = []
    if run_ids:
        findings = list(db.scalars(select(AgentFinding).where(AgentFinding.review_run_id.in_(run_ids))))
        disagreements = list(
            db.scalars(select(AgentDisagreement).where(AgentDisagreement.review_run_id.in_(run_ids)))
        )
        routes = list(db.scalars(select(RoutingDecision).where(RoutingDecision.review_run_id.in_(run_ids))))

    blocking = [f for f in findings if f.status in ("confirmed", "needs_human_review")]
    by_rule = Counter(f.rule_code or "unmapped" for f in blocking)
    by_agent = Counter(f.agent for f in blocking)
    by_severity = Counter(f.severity for f in blocking)

    item_ids = {r.content_version_id for r in runs}
    versions = [db.get(ContentVersion, vid) for vid in item_ids]
    item_map = {v.id: db.get(ContentItem, v.content_item_id) for v in versions if v}
    by_language = Counter(item.language for item in item_map.values() if item)

    brand = db.get(Brand, brand_id)
    policy_rules: list[BrandRule] = list(brand.current_policy.rules) if brand and brand.current_policy else []
    covered = {r.category for r in policy_rules if r.is_authoritative}
    gaps = [c for c in ("tone", "facts", "claims", "visual", "accessibility", "language") if c not in covered]

    resolved = [d for d in disagreements if d.resolution]
    scores = [r.risk_score for r in runs if r.risk_score is not None]
    clearances = list(
        db.scalars(
            select(Clearance).where(
                Clearance.content_version_id.in_([r.content_version_id for r in runs] or [""])
            )
        )
    )
    turnarounds = [
        (r.finished_at - r.started_at).total_seconds()
        for r in runs
        if r.started_at and r.finished_at
    ]

    return {
        "totals": {
            "reviews": len(runs),
            "findings": len(blocking),
            "clearances": len([c for c in clearances if not c.invalidated]),
            "open_disagreements": len(disagreements) - len(resolved),
            "avg_risk": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_review_seconds": round(sum(turnarounds) / len(turnarounds), 2) if turnarounds else 0,
            "rework_rate": round(
                len([r for r in runs if r.status == "needs_changes"]) / len(runs), 2
            )
            if runs
            else 0,
        },
        "by_rule": [{"rule_code": k, "count": v} for k, v in by_rule.most_common()],
        "by_agent": [{"agent": k, "count": v} for k, v in by_agent.most_common()],
        "by_severity": [{"severity": k, "count": v} for k, v in by_severity.most_common()],
        "by_language": [{"language": k, "count": v} for k, v in by_language.most_common()],
        "routes": [{"route": k, "count": v} for k, v in Counter(r.route for r in routes).most_common()],
        "reviewer_agreement": {
            "disagreements": len(disagreements),
            "resolved": len(resolved),
            "agreement_rate": round(1 - (len(disagreements) / max(1, len(findings))), 2),
        },
        "policy_gaps": gaps,
    }
