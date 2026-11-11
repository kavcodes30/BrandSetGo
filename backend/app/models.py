"""SQLAlchemy entities mirroring blueprint section 12 (core data model).

Every reviewable object carries tenant_id + brand_id so that retrieval,
storage and audit are tenant-scoped end to end.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --------------------------------------------------------------------------
# Identity & tenancy
# --------------------------------------------------------------------------
class Organization(Base, Timestamped):
    """A workspace. Creators get one personal workspace; businesses get a team one."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    account_type: Mapped[str] = mapped_column(String(16), default="business")  # creator|business
    plan: Mapped[str] = mapped_column(String(32), default="creator_free")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|suspended
    seats: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    billing_email: Mapped[str] = mapped_column(String(200), default="")


class User(Base, Timestamped):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    avatar_initials: Mapped[str] = mapped_column(String(4), default="")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    account_type: Mapped[str] = mapped_column(String(16), default="business")  # creator|business
    platform_role: Mapped[str | None] = mapped_column(String(16), nullable=True)  # admin|support
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|suspended
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # bumping this revokes every issued session token for the user
    token_version: Mapped[int] = mapped_column(Integer, default=1)


class Membership(Base, Timestamped):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # owner | admin | creator | reviewer | manager | legal | viewer
    role: Mapped[str] = mapped_column(String(24), default="creator")


# --------------------------------------------------------------------------
# Brand, policy, verified facts
# --------------------------------------------------------------------------
class Brand(Base, Timestamped):
    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24), default="business")  # personal|business|agency_client
    sector: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(240), default="")
    tone: Mapped[str] = mapped_column(String(240), default="")
    languages: Mapped[list] = mapped_column(JSON, default=list)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    personality: Mapped[dict] = mapped_column(JSON, default=dict)
    palette: Mapped[dict] = mapped_column(JSON, default=dict)
    logo_url: Mapped[str] = mapped_column(String(240), default="")
    trust_score: Mapped[float] = mapped_column(Float, default=0.6)
    owner_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)

    policy_versions: Mapped[list["PolicyVersion"]] = relationship(
        back_populates="brand", cascade="all, delete-orphan", order_by="PolicyVersion.version"
    )

    @property
    def current_policy(self) -> "PolicyVersion | None":
        published = [p for p in self.policy_versions if p.status == "published"]
        return max(published, key=lambda p: p.version) if published else None


class PolicyVersion(Base, Timestamped):
    __tablename__ = "policy_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|published|superseded
    source_summary: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    brand: Mapped[Brand] = relationship(back_populates="policy_versions")
    rules: Mapped[list["BrandRule"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class BrandRule(Base, Timestamped):
    __tablename__ = "brand_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(24))  # R-01 ...
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(24))  # tone|facts|claims|visual|accessibility|language
    statement: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(12), default="medium")
    scope: Mapped[list] = mapped_column(JSON, default=list)  # channels the rule applies to
    source_ref: Mapped[str] = mapped_column(String(240), default="")
    evidence_ref: Mapped[str] = mapped_column(String(240), default="")
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=False)
    proposed_by_model: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    policy: Mapped[PolicyVersion] = relationship(back_populates="rules")


class Product(Base, Timestamped):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    sku: Mapped[str] = mapped_column(String(60), default="")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)  # volume_ml, price_inr, ...
    sheet_ref: Mapped[str] = mapped_column(String(120), default="")
    sheet_page: Mapped[int] = mapped_column(Integer, default=1)
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)


class ApprovedClaim(Base, Timestamped):
    __tablename__ = "approved_claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(16), default="verified")  # verified|unverified|expired
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base, Timestamped):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24), default="image")
    content_hash: Mapped[str] = mapped_column(String(80), default="")
    palette: Mapped[list] = mapped_column(JSON, default=list)
    has_logo: Mapped[bool] = mapped_column(Boolean, default=True)
    alt_text: Mapped[str] = mapped_column(String(300), default="")
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1080)


# --------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------
class ContentItem(Base, Timestamped):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(60), default="instagram_caption")
    language: Mapped[str] = mapped_column(String(8), default="en")
    campaign: Mapped[str] = mapped_column(String(120), default="")
    desired_cta: Mapped[str] = mapped_column(String(160), default="")
    audience: Mapped[str] = mapped_column(String(240), default="")
    modality: Mapped[str] = mapped_column(String(24), default="text")  # text|image|document|video|audio|web|campaign
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    versions: Mapped[list["ContentVersion"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ContentVersion.version"
    )


class ContentVersion(Base, Timestamped):
    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("content_item_id", "version", name="uq_content_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    content_item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    body_text: Mapped[str] = mapped_column(Text, default="")
    media_ref: Mapped[str] = mapped_column(String(240), default="")
    content_hash: Mapped[str] = mapped_column(String(80), default="")
    sensitivity: Mapped[str] = mapped_column(String(16), default="internal")
    redaction_map: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # spoken/on-screen copy with timings: [{"start": 0.0, "end": 3.4, "text": "..."}]
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    author_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    item: Mapped[ContentItem] = relationship(back_populates="versions")


# --------------------------------------------------------------------------
# Review, findings, disagreement
# --------------------------------------------------------------------------
class ReviewRun(Base, Timestamped):
    __tablename__ = "review_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    content_version_id: Mapped[str] = mapped_column(String(32), index=True)
    policy_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued|preprocessing|reviewing|needs_changes|needs_human|ready_for_approval|approved|passport_issued|failed
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_band: Mapped[str] = mapped_column(String(16), default="pending")
    risk_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    completeness: Mapped[dict] = mapped_column(JSON, default=dict)
    routing: Mapped[dict] = mapped_column(JSON, default=dict)
    hard_blocker: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str] = mapped_column(String(80), default="deterministic")
    modality: Mapped[str] = mapped_column(String(24), default="text")
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80), default="")

    findings: Mapped[list["AgentFinding"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    disagreements: Mapped[list["AgentDisagreement"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    patches: Mapped[list["RewritePatch"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentFinding(Base, Timestamped):
    __tablename__ = "agent_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(ForeignKey("review_runs.id", ondelete="CASCADE"), index=True)
    finding_ref: Mapped[str] = mapped_column(String(40), default="")
    agent: Mapped[str] = mapped_column(String(20))  # tone|facts|claims|visual|accessibility|language
    rule_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule_code: Mapped[str] = mapped_column(String(24), default="")
    severity: Mapped[str] = mapped_column(String(12), default="low")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # confirmed | needs_human_review | inconclusive | pass
    status: Mapped[str] = mapped_column(String(24), default="confirmed")
    span_start: Mapped[int] = mapped_column(Integer, default=0)
    span_end: Mapped[int] = mapped_column(Integer, default=0)
    span_text: Mapped[str] = mapped_column(String(400), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    suggested_patch: Mapped[dict] = mapped_column(JSON, default=dict)
    # deterministic | sarvam
    source: Mapped[str] = mapped_column(String(16), default="deterministic")
    # legal citation for the exact guideline this finding breaks
    guideline_code: Mapped[str] = mapped_column(String(40), default="")
    guideline_title: Mapped[str] = mapped_column(String(240), default="")
    guideline_authority: Mapped[str] = mapped_column(String(240), default="")
    guideline_citation: Mapped[str] = mapped_column(String(240), default="")
    legal_basis: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    timecode_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    timecode_end: Mapped[float | None] = mapped_column(Float, nullable=True)

    run: Mapped[ReviewRun] = relationship(back_populates="findings")


class AgentDisagreement(Base, Timestamped):
    __tablename__ = "agent_disagreements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(ForeignKey("review_runs.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(200))
    span_text: Mapped[str] = mapped_column(String(400), default="")
    agent_a: Mapped[str] = mapped_column(String(20))
    agent_a_status: Mapped[str] = mapped_column(String(120))
    agent_b: Mapped[str] = mapped_column(String(20))
    agent_b_status: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[ReviewRun] = relationship(back_populates="disagreements")


class RewritePatch(Base, Timestamped):
    __tablename__ = "rewrite_patches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(ForeignKey("review_runs.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start: Mapped[int] = mapped_column(Integer, default=0)
    end: Mapped[int] = mapped_column(Integer, default=0)
    original: Mapped[str] = mapped_column(Text, default="")
    replacement: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    rule_code: Mapped[str] = mapped_column(String(24), default="")
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    # pending | accepted | rejected | edited
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[ReviewRun] = relationship(back_populates="patches")


class DriftCheck(Base, Timestamped):
    __tablename__ = "drift_checks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(String(32), index=True)
    patch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    invariants: Mapped[list] = mapped_column(JSON, default=list)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    blocking_reason: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------
# Risk, routing, approvals, clearance, audit
# --------------------------------------------------------------------------
class RiskPolicy(Base, Timestamped):
    __tablename__ = "risk_policies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    fast_track_max: Mapped[int] = mapped_column(Integer, default=25)
    manager_max: Mapped[int] = mapped_column(Integer, default=70)
    trust_floor: Mapped[float] = mapped_column(Float, default=0.55)
    auto_clear_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class RoutingDecision(Base, Timestamped):
    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(String(32), index=True)
    route: Mapped[str] = mapped_column(String(24))  # fast_track|manager|legal|specialist|re_review
    approver_role: Mapped[str] = mapped_column(String(24), default="manager")
    reason: Mapped[str] = mapped_column(Text, default="")


class Approval(Base, Timestamped):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(String(32), index=True)
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    approver_role: Mapped[str] = mapped_column(String(24), default="manager")
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|approved|changes_requested|rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Clearance(Base, Timestamped):
    __tablename__ = "clearances"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(String(32), index=True)
    content_version_id: Mapped[str] = mapped_column(String(32), index=True)
    content_hash: Mapped[str] = mapped_column(String(80), default="")
    policy_version_id: Mapped[str] = mapped_column(String(32), default="")
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    approver: Mapped[str] = mapped_column(String(120), default="")
    clearance_id: Mapped[str] = mapped_column(String(40), unique=True)
    verification_token: Mapped[str] = mapped_column(String(80), default="")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    invalidated_reason: Mapped[str] = mapped_column(Text, default="")


class AuditEvent(Base, Timestamped):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    brand_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(40), default="")
    object_ref: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AIDisclosure(Base, Timestamped):
    __tablename__ = "ai_disclosures"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    review_run_id: Mapped[str] = mapped_column(String(32), index=True)
    processor: Mapped[str] = mapped_column(String(60), default="Sarvam AI")
    model: Mapped[str] = mapped_column(String(60), default="")
    region: Mapped[str] = mapped_column(String(60), default="")
    sensitivity: Mapped[str] = mapped_column(String(16), default="internal")
    data_categories: Mapped[list] = mapped_column(JSON, default=list)
    redaction_version: Mapped[str] = mapped_column(String(40), default="")
    purpose: Mapped[str] = mapped_column(String(160), default="Pre-publication brand review")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retention: Mapped[str] = mapped_column(String(60), default="30 days")
    outcome: Mapped[str] = mapped_column(String(40), default="completed")


class CoachingEvent(Base, Timestamped):
    __tablename__ = "coaching_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    rule_code: Mapped[str] = mapped_column(String(24), default="")
    category: Mapped[str] = mapped_column(String(24), default="claims")
    lesson_key: Mapped[str] = mapped_column(String(60), default="")


class GlossaryTerm(Base, Timestamped):
    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(String(32), index=True)
    term_en: Mapped[str] = mapped_column(String(120))
    term_hi: Mapped[str] = mapped_column(String(160), default="")
    term_mr: Mapped[str] = mapped_column(String(160), default="")
    prohibited: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(String(240), default="")


class Invoice(Base, Timestamped):
    """A self-serve plan change, recorded like a billing event.

    Test mode: no money moves, but the subscription, the amount and the audit
    trail are real, so the pricing model is exercised end to end.
    """

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[str] = mapped_column(String(32), default="")
    plan_from: Mapped[str] = mapped_column(String(32), default="")
    plan_to: Mapped[str] = mapped_column(String(32), default="")
    amount_inr: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="paid")  # paid|due|void
    mode: Mapped[str] = mapped_column(String(16), default="test")
    created_by: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(240), default="")


class MailMessage(Base, Timestamped):
    """Outbox. Sent over SMTP when configured, always readable in the admin console."""

    __tablename__ = "mail_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    to_email: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="notice")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|sent|failed
    error: Mapped[str] = mapped_column(String(240), default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionToken(Base, Timestamped):
    """Single-use token for password reset (and future email verification)."""

    __tablename__ = "action_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    purpose: Mapped[str] = mapped_column(String(24), default="password_reset")
    token_hash: Mapped[str] = mapped_column(String(80), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdempotencyKey(Base, Timestamped):
    """Makes a repeated POST safe: same key returns the same result."""

    __tablename__ = "idempotency_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    scope: Mapped[str] = mapped_column(String(40), default="")
    response: Mapped[dict] = mapped_column(JSON, default=dict)
