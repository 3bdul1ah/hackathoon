"""Typed state model for the dispute-resolution agent graph.

The graph state is a single Pydantic model so every node has a strongly-typed,
auditable view of the case. LangGraph accepts a Pydantic BaseModel as its state
schema; each node returns a partial dict that is merged into this object.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


IssueType = Literal["item_not_received", "duplicate_charge", "unknown"]
HumanApprovalStatus = Literal["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"]


class AuditEvent(BaseModel):
    """One immutable line in the audit timeline. Written by every node."""
    timestamp: str = Field(default_factory=utcnow_iso)
    node_name: str
    tool_called: Optional[str] = None
    evidence_used: list[str] = Field(default_factory=list)
    risk_score: Optional[int] = None
    decision: Optional[str] = None
    policy_version: Optional[str] = None
    rule_id: Optional[str] = None
    human_approval_status: Optional[str] = None
    customer_notice: Optional[str] = None
    detail: Optional[str] = None


class Evidence(BaseModel):
    """Everything the read tools collected for this case."""
    order: Optional[dict[str, Any]] = None
    payments: list[dict[str, Any]] = Field(default_factory=list)
    shipment: Optional[dict[str, Any]] = None
    customer: Optional[dict[str, Any]] = None
    # Derived facts the policy engine consumes:
    delivery_confirmed: bool = False
    duplicate_charge_confirmed: bool = False
    authorization_hold_present: bool = False

    def sources(self) -> list[str]:
        used: list[str] = []
        if self.order:
            used.append(f"order:{self.order.get('order_id')}")
        for p in self.payments:
            used.append(f"payment:{p.get('payment_id')}")
        if self.shipment:
            used.append(f"shipment:{self.shipment.get('shipment_id')}")
        if self.customer:
            used.append(f"customer:{self.customer.get('customer_id')}")
        return used


class RiskSignal(BaseModel):
    code: str
    description: str
    weight: int
    present: bool
    evidence: Optional[str] = None  # the concrete fact that fired this signal


class PolicyDecision(BaseModel):
    policy_version: str
    rule_id: str
    refund_allowed: bool
    requires_human_review: bool
    action: str
    reason: str
    legal_refs: list[str] = Field(default_factory=list)


class LawCitation(BaseModel):
    article_id: str
    title: str
    text: str
    score: Optional[float] = None
    source: str  # "policy_map" or "retrieval"


class RefundPackage(BaseModel):
    """Assembled by prepare_refund. Money only moves in the separate execute
    step, and only after the eligibility gate (policy + approval + idempotency).

    Lifecycle of `status`:
      PREPARED_PENDING_EXECUTION  -> assembled, not yet executed
      EXECUTED                    -> execute_refund ran (after the gate)
      BLOCKED_PENDING_APPROVAL    -> execute attempted without an approval token
    """
    refund_id: str
    order_id: str
    customer_id: str
    amount: float
    currency: str
    status: str
    reason: str
    requires_human_approval: bool
    approved_by: Optional[str] = None
    prepared_at: str = Field(default_factory=utcnow_iso)
    # Set when execute_refund runs:
    execution_id: Optional[str] = None
    executed_at: Optional[str] = None
    idempotent_replay: bool = False  # True if returned from the ledger, not newly created


class CaseState(BaseModel):
    """The complete, typed state object threaded through every graph node."""

    # --- inputs ---
    case_id: str
    customer_id: str
    order_id: Optional[str] = None
    customer_message: str = ""
    # Human reviewer's decision, injected on resume. None => not yet decided.
    human_decision: Optional[Literal["APPROVE", "REJECT"]] = None
    human_reviewer: Optional[str] = None

    # --- identity verification (collected BEFORE the dispute is processed) ---
    provided_emirates_id: Optional[str] = None
    provided_email: Optional[str] = None
    otp_verified: bool = False
    identity_factors: list[dict] = Field(default_factory=list)

    # --- required state fields (per spec) ---
    issue_type: IssueType = "unknown"
    identity_verified: bool = False
    evidence: Evidence = Field(default_factory=Evidence)
    risk_score: int = 0
    risk_signals: list[RiskSignal] = Field(default_factory=list)
    fraud_band: Optional[str] = None           # LOW / MEDIUM / HIGH
    fraud_typology: Optional[str] = None        # named fraud pattern
    fraud_recommendation: Optional[str] = None  # recommended mitigation
    policy_version: Optional[str] = None
    recommended_action: Optional[str] = None
    legal_citations: list[LawCitation] = Field(default_factory=list)
    legal_basis: Optional[str] = None
    legal_source: Optional[str] = None
    human_approval_status: HumanApprovalStatus = "NOT_REQUIRED"
    audit_events: list[AuditEvent] = Field(default_factory=list)
    customer_notice: str = ""
    current_step: str = "created"

    # --- supporting fields ---
    identity_detail: Optional[str] = None
    policy_decision: Optional[PolicyDecision] = None
    refund_package: Optional[RefundPackage] = None
    prompt_injection_detected: bool = False
    prompt_injection_detail: Optional[str] = None
    final_outcome: Optional[str] = None
    # --- resilience / recovery ---
    evidence_incomplete: bool = False        # primary lookups returned nothing
    tool_failures: list[str] = Field(default_factory=list)
    recovery_notes: list[str] = Field(default_factory=list)
    refund_executed: bool = False
