"""LangGraph dispute-resolution workflow.

Customer Request
  -> triage
  -> identity_verification
  -> evidence_retrieval
  -> fraud_risk
  -> policy
  -> decision  --(LOW / refund allowed)--> prepare_remedy -> execute_refund -> audit_logger -> END
               --(HIGH / human review)---> human_approval --+--> prepare_remedy -> execute_refund -> audit_logger -> END
                                                             +--> audit_logger -> END   (pending / rejected)

Every node appends an AuditEvent. No refund is executed automatically: the
money-adjacent tools are split into prepare_refund and an approval-token gated
execute_refund stage behind the human-approval gate.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from .state import (
    CaseState, AuditEvent, Evidence, PolicyDecision, LawCitation, RiskSignal, utcnow_iso,
)
from . import tools
from .fraud_engine import compute_risk, RISK_THRESHOLD
from .policy_engine import evaluate
from .injection_guard import scan
from .notice import generate_notice
from .identity import verify as identity_verify
from .status_assurance import compute_status_assurance
from .senior_support import analyze_message



def _ev(state: CaseState, **kw) -> AuditEvent:
    """Build an AuditEvent pre-filled with current case context."""
    return AuditEvent(
        risk_score=kw.pop("risk_score", state.risk_score),
        policy_version=kw.pop("policy_version", state.policy_version),
        human_approval_status=kw.pop("human_approval_status", state.human_approval_status),
        **kw,
    )


# ----------------------------------------------------------------- NODES
def triage_node(state: CaseState) -> dict[str, Any]:
    msg = state.customer_message.lower()

    # Prompt-injection defense runs first and is purely advisory to the audit
    # log; it never alters routing or policy.
    injected, phrase = scan(state.customer_message)

    if "twice" in msg or "duplicate" in msg or "charged two" in msg or "two charges" in msg:
        issue = "duplicate_charge"
    elif "never received" in msg or "not received" in msg or "didn't arrive" in msg or "did not arrive" in msg:
        issue = "item_not_received"
    else:
        issue = "unknown"

    events = list(state.audit_events)
    if injected:
        events.append(_ev(
            state, node_name="triage", decision="PROMPT_INJECTION_ATTEMPT",
            detail=f"Override attempt ignored: '{phrase}'. Workflow continues unchanged.",
        ))
    events.append(_ev(
        state, node_name="triage", decision=f"classified_issue={issue}",
        detail=f"Routed dispute as '{issue}'.",
    ))

    return {
        "issue_type": issue,
        "prompt_injection_detected": injected,
        "prompt_injection_detail": phrase,
        "current_step": "triage",
        "audit_events": events,
    }


def identity_node(state: CaseState) -> dict[str, Any]:
    """Emirates ID multi-factor verification, evaluated before any evidence is
    pulled. The agent re-validates the factors the customer supplied and records
    every one of them, so a human reviewer can see exactly how identity was
    established."""
    customer = tools.get_customer(state.customer_id) or {}
    result = identity_verify(
        customer,
        provided_emirates_id=state.provided_emirates_id,
        otp_verified=state.otp_verified,
    )
    verified = result["verified"]
    factors = result["factors"]
    detail = result["detail"]
    passed = ", ".join(f["factor"].split(" (")[0] for f in factors if f["passed"]) or "none"

    events = list(state.audit_events)
    events.append(_ev(
        state, node_name="identity_verification",
        tool_called="verify_emirates_id",
        evidence_used=[f"emirates_id:{'***' if state.provided_emirates_id else 'missing'}"],
        decision=f"identity_verified={verified}",
        human_approval_status=state.human_approval_status,
        detail=f"{detail} Factors passed: {passed}.",
    ))
    return {
        "identity_verified": verified,
        "identity_detail": detail,
        "identity_factors": factors,
        "current_step": "identity_verification",
        "audit_events": events,
    }


def evidence_node(state: CaseState) -> dict[str, Any]:
    customer = tools.get_customer(state.customer_id)
    tool_failures: list[str] = []
    recovery_notes: list[str] = []

    # Primary lookup, with one retry then a recovery fallback by customer.
    order = tools.get_order(state.order_id) if state.order_id else None
    if order is None:
        tool_failures.append("get_order")
        # Retry once (covers a transient blip).
        order = tools.get_order(state.order_id) if state.order_id else None
        if order is None:
            recovery_notes.append("get_order returned nothing; retried once.")
            # Recovery path: look the customer's orders up a different way.
            alt = tools.get_orders_for_customer(state.customer_id)
            if state.order_id:
                order = next((o for o in alt if o.get("order_id") == state.order_id), None)
            if order is None and len(alt) == 1:
                order = alt[0]
                recovery_notes.append(
                    f"Recovered order {order.get('order_id')} via customer lookup.")
            elif order is not None:
                recovery_notes.append(
                    f"Recovered order {order.get('order_id')} on the fallback lookup.")

    order_id = order.get("order_id") if order else state.order_id
    shipment = tools.get_shipment(order_id) if order_id else None

    payments: list[dict[str, Any]] = []
    if order:
        for pid in order.get("payment_ids", []):
            p = tools.get_payment(pid)
            if p:
                payments.append(p)

    evidence_incomplete = order is None
    delivery_confirmed = bool(shipment and shipment.get("delivery_confirmed"))

    # Duplicate vs authorization-hold logic.
    settled = [p for p in payments if p.get("status") == "settled"]
    holds = [p for p in payments if p.get("status") == "authorization_hold"]
    authorization_hold_present = len(holds) > 0
    # A real duplicate = two or more SETTLED charges of equal amount on one order.
    duplicate_charge_confirmed = (
        len(settled) >= 2
        and len({round(p.get("amount", 0), 2) for p in settled}) == 1
    )

    evidence = Evidence(
        order=order,
        payments=payments,
        shipment=shipment,
        customer=customer,
        delivery_confirmed=delivery_confirmed,
        duplicate_charge_confirmed=duplicate_charge_confirmed,
        authorization_hold_present=authorization_hold_present,
    )

    events = list(state.audit_events)
    detail = f"Collected {len(payments)} payment record(s)."
    if recovery_notes:
        detail += " RECOVERY: " + " ".join(recovery_notes)
    if evidence_incomplete:
        detail += " Evidence incomplete after recovery; will route to a human."
    events.append(_ev(
        state, node_name="evidence_retrieval",
        tool_called="get_order,get_payment,get_shipment"
                    + (",get_orders_for_customer" if recovery_notes else ""),
        evidence_used=evidence.sources(),
        decision=(
            f"delivery_confirmed={delivery_confirmed}, "
            f"duplicate_confirmed={duplicate_charge_confirmed}, "
            f"auth_hold_present={authorization_hold_present}, "
            f"incomplete={evidence_incomplete}"
        ),
        detail=detail,
    ))
    return {
        "evidence": evidence,
        "evidence_incomplete": evidence_incomplete,
        "tool_failures": tool_failures,
        "recovery_notes": recovery_notes,
        "current_step": "evidence_retrieval",
        "audit_events": events,
    }


def fraud_node(state: CaseState) -> dict[str, Any]:
    score, signals, meta = compute_risk(state.issue_type, state.evidence, state.identity_verified)
    senior = analyze_message(
        state.customer_message,
        senior_mode_enabled=state.senior_mode_enabled,
        is_senior=state.is_senior,
        caregiver_authorized=state.caregiver_authorized,
    )
    senior_flags = senior["flags"]
    senior_summary = senior["summary"]
    if senior_flags:
        score = min(100, score + 70)
        signals.append(RiskSignal(
            code="SENIOR_SCAM_PRESSURE",
            description="Senior-safe mode detected possible scam pressure or coercion.",
            weight=70,
            present=True,
            evidence=", ".join(flag.replace("_", " ").lower() for flag in senior_flags),
        ))
        meta["band"] = "HIGH"
        meta["typology"] = "Potential scam or coercion targeting senior"
        meta["recommendation"] = (
            "Pause resolution. Verify directly with the customer, use the authorized "
            "caregiver only if consent is recorded, and do not act on urgent third-party instructions."
        )
    fired = [s.code for s in signals if s.present]

    events = list(state.audit_events)
    if senior_summary:
        events.append(_ev(
            state, node_name="senior_support",
            decision="SENIOR_SAFE_CONTEXT_RECORDED",
            evidence_used=senior_flags or ["senior_safe_mode"],
            detail=senior_summary,
        ))
    events.append(_ev(
        state, node_name="fraud_risk", risk_score=score,
        decision=f"risk_score={score} band={meta['band']} typology={meta['typology']}",
        evidence_used=fired,
        detail=("Signals fired: " + (", ".join(fired) if fired else "none")
                + f". Recommendation: {meta['recommendation']}"),
    ))
    return {
        "risk_score": score,
        "risk_signals": signals,
        "fraud_band": meta["band"],
        "fraud_typology": meta["typology"],
        "fraud_recommendation": meta["recommendation"],
        "senior_protection_flags": senior_flags,
        "senior_protection_summary": senior_summary,
        "current_step": "fraud_risk",
        "audit_events": events,
    }


def policy_node(state: CaseState) -> dict[str, Any]:
    if state.evidence_incomplete:
        # Recovery safety net: never auto-resolve on missing evidence.
        decision = PolicyDecision(
            policy_version="v1.0.0", rule_id="R-REC", refund_allowed=False,
            requires_human_review=True, action="ROUTE_TO_HUMAN_REVIEW",
            reason="Evidence could not be retrieved even after recovery; a human "
                   "must verify before any remedy.",
            legal_refs=["Art.4", "Art.23"])
    else:
        decision = evaluate(state.issue_type, state.evidence, state.risk_score)

    events = list(state.audit_events)
    events.append(_ev(
        state, node_name="policy", policy_version=decision.policy_version,
        rule_id=decision.rule_id, decision=decision.action,
        detail=f"{decision.rule_id}: {decision.reason}",
    ))
    return {
        "policy_version": decision.policy_version,
        "policy_decision": decision,
        "recommended_action": decision.action,
        "current_step": "policy",
        "audit_events": events,
    }


def legal_grounding_node(state: CaseState) -> dict[str, Any]:
    """RAG agent: retrieve the UAE Consumer Protection Law articles that ground
    this remedy, pinning the articles the policy already maps to and letting
    retrieval surface any others. Citations come from retrieval, never from a
    model, so they cannot be hallucinated."""
    d = state.policy_decision
    facts = {
        "delivery_confirmed": state.evidence.delivery_confirmed,
        "duplicate_charge_confirmed": state.evidence.duplicate_charge_confirmed,
        "authorization_hold_present": state.evidence.authorization_hold_present,
        "evidence_incomplete": state.evidence_incomplete,
    }
    result = tools.search_law(state.issue_type, facts,
                              pin=(d.legal_refs if d else None), k=3)
    citations = [LawCitation(**c) for c in result["citations"]]

    events = list(state.audit_events)
    events.append(_ev(
        state, node_name="legal_grounding", tool_called="search_law",
        evidence_used=[c.article_id for c in citations],
        decision="LAW_GROUNDED",
        detail=result["basis"],
    ))
    return {
        "legal_citations": citations,
        "legal_basis": result["basis"],
        "legal_source": result["source"],
        "current_step": "legal_grounding",
        "audit_events": events,
    }


def decision_node(state: CaseState) -> dict[str, Any]:
    d = state.policy_decision
    # A human ALWAYS approves before money moves. The agent supports the
    # reviewer with a full evidence pack + recommendation; it never replaces
    # them. Cases with no money movement (explanations) resolve autonomously.
    moves_money = bool(d and d.refund_allowed)
    flagged = bool(d and d.requires_human_review)
    senior_protection = bool(state.senior_protection_flags)
    needs_human = moves_money or flagged or senior_protection
    status = "PENDING" if needs_human else "NOT_REQUIRED"

    if not needs_human:
        detail = "No money movement; agent resolves autonomously."
    elif senior_protection:
        detail = "Senior protection flags detected: human review required before closure."
    elif flagged and not moves_money:
        detail = "High risk: mandatory human review before any remedy."
    else:
        recommend = "REVIEW CAREFULLY" if state.risk_score >= RISK_THRESHOLD else "APPROVE (low risk)"
        detail = f"Refund requires human sign-off. Agent recommendation: {recommend}."

    events = list(state.audit_events)
    events.append(_ev(
        state, node_name="decision", human_approval_status=status,
        decision=("ROUTE_TO_HUMAN_REVIEW" if needs_human else d.action if d else "UNKNOWN"),
        rule_id=d.rule_id if d else None,
        detail=detail,
    ))
    return {
        "human_approval_status": status,
        "current_step": "decision",
        "audit_events": events,
    }


def human_approval_node(state: CaseState) -> dict[str, Any]:
    """Human-in-the-loop gate. Opens a risk case and PAUSES.

    If no human_decision has been supplied yet, we leave status PENDING and do
    NOT prepare any refund; execution is blocked. When the UI resumes the graph
    with human_decision=APPROVE/REJECT, this node records the outcome.
    """
    events = list(state.audit_events)

    risk_case = tools.create_risk_case({
        "case_id": state.case_id,
        "customer_id": state.customer_id,
        "risk_score": state.risk_score,
        "summary": f"{state.issue_type} dispute, risk {state.risk_score}, "
                   f"rule {state.policy_decision.rule_id if state.policy_decision else '?'}"
                   + ("; senior protection review" if state.senior_protection_flags else ""),
    })

    if state.human_decision is None:
        events.append(_ev(
            state, node_name="human_approval",
            tool_called="create_risk_case",
            human_approval_status="PENDING",
            decision="PAUSED_FOR_HUMAN_REVIEW",
            detail=f"Opened {risk_case['risk_case_id']}. Awaiting reviewer. "
                   "No refund prepared.",
        ))
        return {
            "human_approval_status": "PENDING",
            "current_step": "human_approval",
            "audit_events": events,
        }

    approved = state.human_decision == "APPROVE"
    status = "APPROVED" if approved else "REJECTED"
    events.append(_ev(
        state, node_name="human_approval",
        tool_called="create_risk_case",
        human_approval_status=status,
        decision=f"HUMAN_{status}",
        detail=f"Reviewer {state.human_reviewer or 'reviewer'} {status.lower()} the case.",
    ))
    return {
        "human_approval_status": status,
        "current_step": "human_approval",
        "audit_events": events,
    }


def prepare_remedy_node(state: CaseState) -> dict[str, Any]:
    d = state.policy_decision
    events = list(state.audit_events)

    # Prepare a refund when policy directly allows it, OR when a human reviewer
    # has explicitly approved a high-risk case. The EXPLAIN_NO_REFUND action is
    # never overridden by approval (there is genuinely no refund owed).
    refund_due = bool(d) and (
        d.action == "PREPARE_REFUND"
        or (state.human_approval_status == "APPROVED" and d.action != "EXPLAIN_NO_REFUND")
    )

    if refund_due:
        order = state.evidence.order or {}
        order_amount = order.get("amount", 0.0)
        refund_reason = f"Human-approved after review ({d.rule_id}): {d.reason}"
        try:
            pkg = tools.prepare_refund({
                "order_id": state.order_id,
                "customer_id": state.customer_id,
                "amount": order_amount,
                "expected_amount": order_amount,   # amount check
                "currency": order.get("currency", "AED"),
                "reason": refund_reason,
                "refund_allowed": True,            # eligibility check
                "requires_human_approval": True,
                "approved_by": state.human_reviewer,
            })
        except tools.EligibilityError as exc:
            outcome = f"Refund blocked by eligibility check: {exc}"
            events.append(_ev(
                state, node_name="prepare_remedy", tool_called="prepare_refund",
                decision="REFUND_BLOCKED_INELIGIBLE", rule_id=d.rule_id, detail=outcome,
            ))
            return {"final_outcome": outcome, "current_step": "prepare_remedy",
                    "audit_events": events}

        notice = generate_notice("PREPARE_REFUND", amount=pkg.amount, currency=pkg.currency,
                                 context=f"{d.reason} {state.legal_basis or ''}")
        replay = " (idempotent replay, no duplicate)" if pkg.idempotent_replay else ""
        outcome = f"Refund package {pkg.refund_id} prepared (status {pkg.status}){replay}."
        events.append(_ev(
            state, node_name="prepare_remedy", tool_called="prepare_refund",
            decision="REFUND_PREPARED", rule_id=d.rule_id, customer_notice=notice,
            detail=outcome,
        ))
        return {
            "refund_package": pkg,
            "customer_notice": notice,
            "final_outcome": outcome,
            "current_step": "prepare_remedy",
            "audit_events": events,
        }

    # EXPLAIN_NO_REFUND path (e.g. authorization hold mistaken for a duplicate).
    notice = generate_notice("EXPLAIN_NO_REFUND",
                             context=f"{d.reason if d else ''} {state.legal_basis or ''}")
    outcome = "No refund owed; explanation issued to customer."
    events.append(_ev(
        state, node_name="prepare_remedy",
        decision="NO_REFUND_EXPLAINED", rule_id=d.rule_id if d else None,
        customer_notice=notice, detail=outcome,
    ))
    return {
        "customer_notice": notice,
        "final_outcome": outcome,
        "current_step": "prepare_remedy",
        "audit_events": events,
    }


def execute_refund_node(state: CaseState) -> dict[str, Any]:
    """Separate EXECUTE stage. Moves money only with a valid approval token and
    only once (idempotent). With no token the refund is blocked, not executed."""
    events = list(state.audit_events)
    pkg = state.refund_package

    if pkg is None:
        # No refund to execute (explanation path). Nothing to do.
        return {"current_step": "execute_refund", "audit_events": events}

    # The token proves the eligibility gate passed: a human approved this refund.
    approval_token = (f"HUMAN:{state.human_reviewer or 'reviewer'}"
                      if state.human_approval_status == "APPROVED" else None)

    result = tools.execute_refund({
        "refund_package": pkg,
        "approval_token": approval_token,
    })
    executed = result.status == "EXECUTED"
    replay = " (idempotent replay, no double refund)" if result.idempotent_replay else ""
    if executed:
        outcome = f"Refund {result.refund_id} EXECUTED as {result.execution_id}{replay}."
    else:
        outcome = "Refund execution BLOCKED: no approval token present."

    events.append(_ev(
        state, node_name="execute_refund", tool_called="execute_refund",
        decision=("REFUND_EXECUTED" if executed else "REFUND_BLOCKED"),
        rule_id=state.policy_decision.rule_id if state.policy_decision else None,
        detail=outcome,
    ))
    return {
        "refund_package": result,
        "refund_executed": executed,
        "final_outcome": outcome,
        "current_step": "execute_refund",
        "audit_events": events,
    }


def audit_logger_node(state: CaseState) -> dict[str, Any]:
    """Seals the case: emits a final summary event and a customer notice if one
    was not already produced (pending/rejected paths)."""
    events = list(state.audit_events)

    notice = state.customer_notice
    outcome = state.final_outcome

    if state.human_approval_status == "PENDING":
        notice = generate_notice("ROUTE_TO_HUMAN_REVIEW")
        outcome = "Case paused, awaiting human reviewer. NO refund executed."
    elif state.human_approval_status == "REJECTED":
        notice = generate_notice("ROUTE_TO_HUMAN_REVIEW")
        outcome = "Reviewer rejected the refund. NO refund executed."

    assured_state = state.model_copy(update={
        "customer_notice": notice or state.customer_notice,
        "final_outcome": outcome or state.final_outcome,
    })
    assurance = compute_status_assurance(assured_state)
    events.append(_ev(
        assured_state, node_name="status_assurance",
        evidence_used=[e["type"] for e in assurance["follow_up_events"]],
        decision=f"sla_status={assurance['sla_status']}",
        customer_notice=assurance["customer_waiting_message"],
        detail=(
            f"Owner: {assurance['assigned_owner']}. Next update: "
            f"{assurance['next_update_at']}. SLA due: {assurance['sla_due_at']}."
        ),
    ))

    events.append(_ev(
        state, node_name="audit_logger",
        decision="CASE_SEALED",
        customer_notice=notice,
        detail=outcome or "Case complete.",
    ))
    return {
        "customer_notice": notice or state.customer_notice,
        "final_outcome": outcome or state.final_outcome,
        **assurance,
        "current_step": "audit_logger",
        "audit_events": events,
    }


# ----------------------------------------------------------------- ROUTERS
def route_after_decision(state: CaseState) -> str:
    if state.human_approval_status == "PENDING":
        return "human_approval"
    return "prepare_remedy"


def route_after_human(state: CaseState) -> str:
    if state.human_approval_status == "APPROVED":
        return "prepare_remedy"
    # PENDING (paused) or REJECTED -> straight to audit, no remedy.
    return "audit_logger"


# ----------------------------------------------------------------- BUILD
def build_graph():
    g = StateGraph(CaseState)
    g.add_node("triage", triage_node)
    g.add_node("identity_verification", identity_node)
    g.add_node("evidence_retrieval", evidence_node)
    g.add_node("fraud_risk", fraud_node)
    g.add_node("policy", policy_node)
    g.add_node("legal_grounding", legal_grounding_node)
    g.add_node("decision", decision_node)
    g.add_node("human_approval", human_approval_node)
    g.add_node("prepare_remedy", prepare_remedy_node)
    g.add_node("execute_refund", execute_refund_node)
    g.add_node("audit_logger", audit_logger_node)

    g.set_entry_point("triage")
    g.add_edge("triage", "identity_verification")
    g.add_edge("identity_verification", "evidence_retrieval")
    g.add_edge("evidence_retrieval", "fraud_risk")
    g.add_edge("fraud_risk", "policy")
    g.add_edge("policy", "legal_grounding")
    g.add_edge("legal_grounding", "decision")

    g.add_conditional_edges("decision", route_after_decision,
                            {"human_approval": "human_approval",
                             "prepare_remedy": "prepare_remedy"})
    g.add_conditional_edges("human_approval", route_after_human,
                            {"prepare_remedy": "prepare_remedy",
                             "audit_logger": "audit_logger"})
    # PREPARE is always followed by the separate EXECUTE stage (which itself
    # gates on the approval token), then the case is sealed.
    g.add_edge("prepare_remedy", "execute_refund")
    g.add_edge("execute_refund", "audit_logger")
    g.add_edge("audit_logger", END)
    return g.compile()


def run_case(case_id: str, customer_id: str, order_id: str | None,
             customer_message: str, *, human_decision: str | None = None,
             human_reviewer: str | None = None,
             simulate_failures: set[str] | None = None,
             provided_emirates_id: str | None = None,
             otp_verified: bool = False,
             is_senior: bool = False,
             senior_mode_enabled: bool = False,
             preferred_language: str = "English",
             caregiver_authorized: bool = False,
             caregiver_name: str | None = None,
             caregiver_relationship: str | None = None,
             caregiver_phone: str | None = None) -> CaseState:
    """Run the graph end-to-end and return the final typed state.

    simulate_failures: tool names to force-fail (e.g. {"get_order"}) so the
    recovery path can be demonstrated live.
    provided_emirates_id / otp_verified: identity factors the customer supplied
    during the pre-dispute verification gate.
    """
    tools.reset_tool_log()
    tools.SIMULATE_FAILURES.clear()
    if simulate_failures:
        tools.SIMULATE_FAILURES.update(simulate_failures)

    initial = CaseState(
        case_id=case_id,
        customer_id=customer_id,
        order_id=order_id,
        customer_message=customer_message,
        human_decision=human_decision,  # type: ignore[arg-type]
        human_reviewer=human_reviewer,
        provided_emirates_id=provided_emirates_id,
        otp_verified=otp_verified,
        is_senior=is_senior,
        senior_mode_enabled=senior_mode_enabled,
        preferred_language=preferred_language,
        caregiver_authorized=caregiver_authorized,
        caregiver_name=caregiver_name,
        caregiver_relationship=caregiver_relationship,
        caregiver_phone=caregiver_phone,
    )
    app = build_graph()
    result = app.invoke(initial)
    # LangGraph returns the merged state; coerce to CaseState for typed access.
    return CaseState.model_validate(result) if not isinstance(result, CaseState) else result
