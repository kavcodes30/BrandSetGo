from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import Ctx, get_ctx
from app.api.serialize import iso, review_summary
from app.models import Approval, AuditEvent, Brand, ContentVersion, ReviewRun, utcnow
from app.schemas import ApprovalDecision, ApprovalRequest
from app.services import passport

router = APIRouter(prefix="/approvals", tags=["approvals"])

ROLE_FOR_ROUTE = {"fast_track": "owner", "manager": "manager", "legal": "legal", "specialist": "reviewer"}


@router.get("")
def list_approvals(status: str | None = None, ctx: Ctx = Depends(get_ctx)):
    stmt = select(Approval).where(Approval.status == status) if status else select(Approval)
    rows = list(ctx.db.scalars(stmt.order_by(Approval.created_at.desc())))
    out = []
    for row in rows:
        run = ctx.db.get(ReviewRun, row.review_run_id)
        if run is None or run.org_id != ctx.org.id:
            continue
        summary = review_summary(ctx.db, run)
        out.append(
            {
                "id": row.id,
                "status": row.status,
                "approver_role": row.approver_role,
                "requested_by": row.requested_by,
                "decided_by": row.decided_by,
                "decided_at": iso(row.decided_at),
                "comment": row.comment,
                "created_at": iso(row.created_at),
                "review": summary,
            }
        )
    return out


@router.post("", status_code=201)
def request_approval(payload: ApprovalRequest, review_run_id: str, ctx: Ctx = Depends(get_ctx)):
    ctx.require("creator")
    run = ctx.db.get(ReviewRun, review_run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Review not found in this workspace.")
    if run.status in ("needs_changes",):
        raise HTTPException(
            status_code=400,
            detail="This review still has open findings. Fix them or create a revised version first.",
        )
    route = (run.routing or {}).get("route", "manager")
    existing = ctx.db.scalars(
        select(Approval).where(Approval.review_run_id == run.id, Approval.status == "pending")
    ).first()
    if existing:
        return {"id": existing.id, "status": existing.status, "approver_role": existing.approver_role}

    row = Approval(
        review_run_id=run.id,
        requested_by=payload.requested_by or ctx.user.name,
        approver_role=payload.approver_role or ROLE_FOR_ROUTE.get(route, "manager"),
        status="pending",
    )
    ctx.db.add(row)
    run.status = "ready_for_approval"
    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=run.brand_id,
            actor=ctx.user.name,
            action="approval.requested",
            object_type="review_run",
            object_ref=run.id,
            detail={"approver_role": row.approver_role, "route": route},
        )
    )
    ctx.db.commit()
    return {"id": row.id, "status": row.status, "approver_role": row.approver_role}


@router.post("/{approval_id}/decision")
def decide(approval_id: str, payload: ApprovalDecision, ctx: Ctx = Depends(get_ctx)):
    ctx.require("reviewer")
    row = ctx.db.get(Approval, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    run = ctx.db.get(ReviewRun, row.review_run_id)
    if run is None or run.org_id != ctx.org.id:
        raise HTTPException(status_code=404, detail="Approval not found in this workspace.")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="This approval has already been decided.")

    if payload.decision == "approved":
        if row.approver_role == "legal":
            ctx.require("legal")
        elif row.approver_role == "manager":
            ctx.require("manager")
        if run.hard_blocker:
            raise HTTPException(
                status_code=409,
                detail="A critical finding blocks approval. Resolve it or record a legal override first.",
            )

    row.status = payload.decision
    row.comment = payload.comment
    row.decided_by = payload.decided_by or ctx.user.name
    row.decided_at = utcnow()

    clearance = None
    if payload.decision == "approved":
        content = ctx.db.get(ContentVersion, run.content_version_id)
        brand = ctx.db.get(Brand, run.brand_id)
        policy = brand.current_policy if brand else None
        clearance = passport.issue(ctx.db, run, content, policy, row.decided_by)
        run.status = "passport_issued"
    elif payload.decision == "changes_requested":
        run.status = "needs_changes"
    else:
        run.status = "needs_changes"

    ctx.db.add(
        AuditEvent(
            org_id=ctx.org.id,
            brand_id=run.brand_id,
            actor=row.decided_by,
            action=f"approval.{payload.decision}",
            object_type="review_run",
            object_ref=run.id,
            detail={"comment": payload.comment, "clearance": clearance.clearance_id if clearance else None},
        )
    )
    ctx.db.commit()
    return {
        "approval": {"id": row.id, "status": row.status, "decided_by": row.decided_by},
        "review_status": run.status,
        "clearance_id": clearance.clearance_id if clearance else None,
    }
