"""Pydantic contracts.

Agent output is validated through FindingDraft before it is persisted: model
text is treated as untrusted input, exactly as blueprint section 23 requires.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
AgentName = Literal["tone", "facts", "claims", "visual", "accessibility", "language", "legal"]
FindingStatus = Literal["confirmed", "needs_human_review", "inconclusive", "pass"]
Sensitivity = Literal["public", "internal", "confidential", "restricted"]


class SuggestedPatch(BaseModel):
    replacement: str
    reason: str
    rule_code: str = ""


class FindingDraft(BaseModel):
    """One checker's conclusion. Shape is enforced before persistence."""

    agent: AgentName
    rule_code: str = ""
    title: str = ""
    severity: Severity = "low"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: FindingStatus = "confirmed"
    span_text: str = ""
    explanation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_patch: SuggestedPatch | None = None
    # which layer produced this finding: the deterministic checker or the model
    source: Literal["deterministic", "sarvam"] = "deterministic"
    # legal citation: the exact guideline a finding breaks, and what to change
    guideline_code: str = ""
    guideline_title: str = ""
    guideline_authority: str = ""
    guideline_citation: str = ""
    legal_basis: str = ""
    remediation: str = ""
    timecode_start: float | None = None
    timecode_end: float | None = None


# ---------------------------------------------------------------- requests
class BrandCreate(BaseModel):
    name: str
    kind: Literal["personal", "business", "agency_client"] = "business"
    sector: str = ""
    description: str = ""
    audience: str = ""
    tone: str = ""
    languages: list[str] = Field(default_factory=lambda: ["en"])
    channels: list[str] = Field(default_factory=lambda: ["instagram_caption"])
    personality: dict = Field(default_factory=dict)
    palette: dict = Field(default_factory=dict)
    logo_url: str = ""
    starter_questionnaire: dict = Field(default_factory=dict)


class RuleDraft(BaseModel):
    code: str
    title: str
    category: Literal["tone", "facts", "claims", "visual", "accessibility", "language"]
    statement: str
    severity: Severity = "medium"
    scope: list[str] = Field(default_factory=list)
    source_ref: str = ""
    evidence_ref: str = ""


class PolicyImport(BaseModel):
    source_summary: str = ""
    rules: list[RuleDraft] = Field(default_factory=list)
    # paste brand guidelines and let Sarvam extract enforceable rules
    guideline_text: str = ""


class PolicyApprove(BaseModel):
    approver: str = ""
    rule_codes: list[str] = Field(default_factory=list)


class ClaimCreate(BaseModel):
    text: str
    product_id: str | None = None
    evidence_ref: str = ""
    status: Literal["verified", "unverified", "expired"] = "verified"


class ProductCreate(BaseModel):
    name: str
    sku: str = ""
    attributes: dict = Field(default_factory=dict)
    sheet_ref: str = ""
    sheet_page: int = 1


class TranscriptSegment(BaseModel):
    start: float = 0.0
    end: float = 0.0
    text: str


class TranscriptUpload(BaseModel):
    """SRT, VTT or timestamped text pasted by the creator."""

    content: str
    format: Literal["srt", "vtt", "text", "auto"] = "auto"


class ContentCreate(BaseModel):
    brand_id: str
    title: str
    body_text: str = ""
    channel: str = "instagram_caption"
    language: str = "en"
    campaign: str = ""
    desired_cta: str = ""
    audience: str = ""
    modality: str = "text"
    media_ref: str = ""
    sensitivity: Sensitivity = "internal"
    meta: dict = Field(default_factory=dict)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    duration_s: float = 0.0


class ContentRevision(BaseModel):
    body_text: str
    meta: dict = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    content_version_id: str


class PatchDecision(BaseModel):
    decision: Literal["accepted", "rejected", "edited"]
    edited_text: str | None = None
    decided_by: str = ""


class DisagreementResolution(BaseModel):
    resolution: str
    resolved_by: str = ""


class ApprovalRequest(BaseModel):
    approver_role: str = "manager"
    requested_by: str = ""


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "changes_requested", "rejected"]
    comment: str = ""
    decided_by: str = ""


class RiskPolicyUpdate(BaseModel):
    fast_track_max: int = 25
    manager_max: int = 70
    trust_floor: float = 0.55
    auto_clear_enabled: bool = False


class GlossaryCreate(BaseModel):
    term_en: str
    term_hi: str = ""
    term_mr: str = ""
    prohibited: list[str] = Field(default_factory=list)
    notes: str = ""


class QuickCheckRequest(BaseModel):
    body_text: str
    language: str = "en"
    channel: str = "instagram_caption"


# ---------------------------------------------------------------- accounts
class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200)
    # length rules live in one place (services/auth.py) so the API returns a
    # readable message instead of a 422 validation dump
    password: str = Field(min_length=1, max_length=200)
    account_type: Literal["creator", "business"]
    # business only
    company: str = ""
    plan: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    billing_email: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class MemberInvite(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "manager", "legal", "reviewer", "creator", "viewer"] = "creator"


class MemberRoleUpdate(BaseModel):
    role: Literal["admin", "manager", "legal", "reviewer", "creator", "viewer"]


class PlanChange(BaseModel):
    plan: str


class StatusChange(BaseModel):
    status: Literal["active", "suspended"]


# ------------------------------------------------------------- account flows
class ResetRequest(BaseModel):
    email: str


class ResetPassword(BaseModel):
    token: str
    password: str = Field(min_length=1, max_length=200)


class SwitchWorkspace(BaseModel):
    org_id: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    account_type: Literal["creator", "business"]
    plan: str = ""


class CheckoutRequest(BaseModel):
    plan: str
