"""Creator coaching: repeated mistakes become short, private lessons."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import as_utc
from app.models import AgentFinding, CoachingEvent, ReviewRun, utcnow
from app.services.reviews import LESSONS


def summary(db: Session, brand_id: str) -> dict:
    events = list(db.scalars(select(CoachingEvent).where(CoachingEvent.brand_id == brand_id)))
    counts = Counter(e.rule_code for e in events if e.rule_code)

    examples: dict[str, dict] = {}
    runs = list(
        db.scalars(
            select(ReviewRun).where(ReviewRun.brand_id == brand_id).order_by(ReviewRun.created_at.desc())
        )
    )
    for run in runs:
        for f in db.scalars(select(AgentFinding).where(AgentFinding.review_run_id == run.id)):
            if f.rule_code and f.rule_code not in examples and f.status != "pass":
                examples[f.rule_code] = {
                    "span": f.span_text,
                    "explanation": f.explanation,
                    "review_run_id": run.id,
                    "category": f.agent,
                }

    top = [
        {
            "rule_code": code,
            "category": examples.get(code, {}).get("category", "claims"),
            "count": count,
            "lesson": LESSONS.get(code, "Review this rule before your next submission."),
            "example": examples.get(code, {}),
        }
        for code, count in counts.most_common(3)
    ]

    now = utcnow()
    weeks = []
    for i in range(5, -1, -1):
        start = now - timedelta(days=7 * (i + 1))
        end = now - timedelta(days=7 * i)
        weeks.append(
            {
                "week_start": start.date().isoformat(),
                "count": sum(1 for e in events if as_utc(e.created_at) and start <= as_utc(e.created_at) < end),
            }
        )

    return {
        "top_issues": top,
        "total_events": len(events),
        "trend": weeks,
        "private_by_default": True,
        "lessons": [{"rule_code": c, "text": LESSONS.get(c, "")} for c in counts],
    }
