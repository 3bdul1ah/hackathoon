"""Least-privilege tools.

Design rules enforced here:
  * READ tools (get_order / get_payment / get_shipment) can ONLY read mock data.
  * RISK tool (create_risk_case) opens a review case; it cannot move money.
  * ACTION tool (prepare_refund) ONLY assembles a refund package. There is
    deliberately NO execute_refund tool anywhere in the system.
  * TOOL_PERMISSIONS pins exactly which node may call which tool, so least
    privilege is verifiable, not just asserted.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .state import RefundPackage, utcnow_iso as _now_iso

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> dict[str, Any]:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# --- Tool-call ledger (for the audit trail + UI "Tool Calls" view) ---
TOOL_CALL_LOG: list[dict[str, Any]] = []


def _record(tool: str, args: dict[str, Any], ok: bool, summary: str) -> None:
    TOOL_CALL_LOG.append(
        {"tool": tool, "args": args, "ok": ok, "summary": summary}
    )


def reset_tool_log() -> None:
    TOOL_CALL_LOG.clear()


# Fault injection for the demo: any tool name in this set behaves as if the
# backing service is down (returns nothing), so the agent's recovery path can be
# shown live. Managed by run_case(simulate_failures=...).
SIMULATE_FAILURES: set[str] = set()


# Idempotency ledgers (persist across runs within a process). Keyed by order_id
# so the same refund can never be prepared or executed twice.
REFUND_LEDGER: dict[str, RefundPackage] = {}
EXECUTION_LEDGER: dict[str, str] = {}  # order_id -> execution_id


def reset_ledgers() -> None:
    REFUND_LEDGER.clear()
    EXECUTION_LEDGER.clear()


# Least-privilege matrix: node -> tools it is permitted to call.
# READ / RISK / PREPARE / EXECUTE are each isolated to their own node.
TOOL_PERMISSIONS: dict[str, set[str]] = {
    "triage": set(),
    "identity_verification": set(),  # uses mocked customer record, no money tools
    "evidence_retrieval": {"get_order", "get_payment", "get_shipment",
                           "get_orders_for_customer"},
    "fraud_risk": set(),
    "policy": set(),
    "legal_grounding": {"search_law"},   # RAG: read-only over the law KB
    "decision": set(),
    "human_approval": {"create_risk_case"},
    "prepare_remedy": {"prepare_refund"},   # may PREPARE, may not EXECUTE
    "execute_refund": {"execute_refund"},   # may EXECUTE, may not PREPARE
    "audit_logger": set(),
}


class PermissionError_(Exception):
    pass


def _check(node: str, tool: str) -> None:
    allowed = TOOL_PERMISSIONS.get(node, set())
    if tool not in allowed:
        raise PermissionError_(
            f"Least-privilege violation: node '{node}' may not call '{tool}'. "
            f"Allowed: {sorted(allowed) or 'none'}"
        )


# ---------------------------------------------------------------- READ TOOLS
def _is_down(tool: str) -> bool:
    return tool in SIMULATE_FAILURES


def get_order(order_id: str, _node: str = "evidence_retrieval") -> dict[str, Any] | None:
    _check(_node, "get_order")
    if _is_down("get_order"):
        _record("get_order", {"order_id": order_id}, False,
                "SERVICE_UNAVAILABLE (simulated outage)")
        return None
    order = _load("orders.json").get(order_id)
    _record("get_order", {"order_id": order_id}, order is not None,
            f"order {order_id} -> {order.get('status') if order else 'NOT_FOUND'}")
    return order


def get_orders_for_customer(customer_id: str, _node: str = "evidence_retrieval") -> list[dict[str, Any]]:
    """Recovery lookup: find a customer's orders when a direct id lookup fails."""
    _check(_node, "get_orders_for_customer")
    orders = [o for o in _load("orders.json").values() if o.get("customer_id") == customer_id]
    _record("get_orders_for_customer", {"customer_id": customer_id}, bool(orders),
            f"found {len(orders)} order(s) for {customer_id}")
    return orders


def get_payment(payment_id: str, _node: str = "evidence_retrieval") -> dict[str, Any] | None:
    _check(_node, "get_payment")
    pay = _load("payments.json").get(payment_id)
    _record("get_payment", {"payment_id": payment_id}, pay is not None,
            f"payment {payment_id} -> {pay.get('status') if pay else 'NOT_FOUND'}")
    return pay


def get_shipment(order_id: str, _node: str = "evidence_retrieval") -> dict[str, Any] | None:
    _check(_node, "get_shipment")
    ship = _load("shipments.json").get(order_id)
    _record("get_shipment", {"order_id": order_id}, ship is not None,
            f"shipment for {order_id} -> {ship.get('status') if ship else 'NOT_FOUND'}")
    return ship


# Not a tool the graph routes through, but a legitimate mocked read.
def get_customer(customer_id: str) -> dict[str, Any] | None:
    return _load("customers.json").get(customer_id)


def search_law(issue_type: str, facts: dict[str, Any], pin: list[str] | None = None,
               k: int = 3, _node: str = "legal_grounding") -> dict[str, Any]:
    """RAG read tool: retrieve relevant UAE Consumer Protection Law articles."""
    _check(_node, "search_law")
    from .rag import ground
    result = ground(issue_type, facts, pin=pin, k=k)
    _record("search_law", {"issue_type": issue_type, "pin": pin or []}, True,
            f"retrieved {len(result['citations'])} article(s): "
            + ", ".join(c["article_id"] for c in result["citations"]))
    return result


# ---------------------------------------------------------------- RISK TOOL
def create_risk_case(case_data: dict[str, Any], _node: str = "human_approval") -> dict[str, Any]:
    _check(_node, "create_risk_case")
    risk_case = {
        "risk_case_id": "RC-" + uuid.uuid4().hex[:8].upper(),
        "case_id": case_data.get("case_id"),
        "customer_id": case_data.get("customer_id"),
        "risk_score": case_data.get("risk_score"),
        "queue": "MANUAL_REVIEW",
        "status": "OPEN",
        "summary": case_data.get("summary", ""),
    }
    _record("create_risk_case", {"case_id": case_data.get("case_id")}, True,
            f"opened {risk_case['risk_case_id']} in MANUAL_REVIEW queue")
    return risk_case


class EligibilityError(Exception):
    pass


# ---------------------------------------------------------------- PREPARE TOOL
def prepare_refund(refund_request: dict[str, Any], _node: str = "prepare_remedy") -> RefundPackage:
    """Assemble a refund package. Runs amount + eligibility + idempotency checks.

    This tool NEVER moves money; that is execute_refund's job, behind the gate.
    """
    _check(_node, "prepare_refund")
    order_id = refund_request["order_id"]

    # --- IDEMPOTENCY: one prepared refund per order. Replay the existing one. ---
    if order_id in REFUND_LEDGER:
        existing = REFUND_LEDGER[order_id].model_copy(update={"idempotent_replay": True})
        _record("prepare_refund", {"order_id": order_id}, True,
                f"idempotent replay -> existing {existing.refund_id} (no duplicate created)")
        return existing

    # --- ELIGIBILITY / AMOUNT checks before any refund is assembled. ---
    amount = refund_request.get("amount")
    expected = refund_request.get("expected_amount")
    if amount is None or amount <= 0:
        _record("prepare_refund", {"order_id": order_id, "amount": amount}, False,
                "REJECTED: non-positive or missing amount")
        raise EligibilityError(f"Refund amount must be positive, got {amount!r}.")
    if expected is not None and round(float(amount), 2) != round(float(expected), 2):
        _record("prepare_refund", {"order_id": order_id, "amount": amount}, False,
                f"REJECTED: amount {amount} != order amount {expected}")
        raise EligibilityError(f"Refund amount {amount} does not match order amount {expected}.")
    if not refund_request.get("refund_allowed", False):
        _record("prepare_refund", {"order_id": order_id}, False,
                "REJECTED: policy does not allow a refund")
        raise EligibilityError("Policy does not allow a refund for this case.")

    pkg = RefundPackage(
        refund_id="RF-" + uuid.uuid4().hex[:8].upper(),
        order_id=order_id,
        customer_id=refund_request["customer_id"],
        amount=amount,
        currency=refund_request.get("currency", "AED"),
        status="PREPARED_PENDING_EXECUTION",
        reason=refund_request.get("reason", ""),
        requires_human_approval=refund_request.get("requires_human_approval", False),
        approved_by=refund_request.get("approved_by"),
    )
    REFUND_LEDGER[order_id] = pkg
    _record("prepare_refund", {"order_id": order_id, "amount": amount}, True,
            f"prepared {pkg.refund_id} status={pkg.status} (checks passed, NOT executed)")
    return pkg


# ---------------------------------------------------------------- EXECUTE TOOL
def execute_refund(execute_request: dict[str, Any], _node: str = "execute_refund") -> RefundPackage:
    """Move the money. Separated from prepare, gated, and idempotent.

    The caller must pass an `approval_token` that proves the eligibility gate
    passed (human approval OR a policy auto-allow with no review required). With
    no token, the refund is BLOCKED, never executed.
    """
    _check(_node, "execute_refund")
    pkg: RefundPackage = execute_request["refund_package"]
    approval_token = execute_request.get("approval_token")

    # --- GATE: no token => never execute. ---
    if not approval_token:
        blocked = pkg.model_copy(update={"status": "BLOCKED_PENDING_APPROVAL"})
        _record("execute_refund", {"refund_id": pkg.refund_id}, False,
                "BLOCKED: no approval token; refund not executed")
        return blocked

    # --- IDEMPOTENCY: never execute the same order's refund twice. ---
    if pkg.order_id in EXECUTION_LEDGER:
        exec_id = EXECUTION_LEDGER[pkg.order_id]
        done = pkg.model_copy(update={"status": "EXECUTED", "execution_id": exec_id,
                                      "idempotent_replay": True})
        _record("execute_refund", {"refund_id": pkg.refund_id}, True,
                f"idempotent replay -> already executed as {exec_id} (no double refund)")
        return done

    exec_id = "EX-" + uuid.uuid4().hex[:8].upper()
    EXECUTION_LEDGER[pkg.order_id] = exec_id
    done = pkg.model_copy(update={"status": "EXECUTED", "execution_id": exec_id,
                                  "executed_at": _now_iso()})
    _record("execute_refund", {"refund_id": pkg.refund_id, "amount": pkg.amount}, True,
            f"EXECUTED {pkg.refund_id} as {exec_id} (token={approval_token})")
    return done
