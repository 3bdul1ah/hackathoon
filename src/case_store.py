"""In-process shared case store.

The Customer page writes a case here when a request is submitted; the Staff
console reads the queue and updates a case when a reviewer approves or rejects.
A module-level dict persists across Streamlit reruns within the same server
process, so both pages see the same cases without a database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

CASES: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status_of(state) -> str:
    """Human-readable lifecycle status derived from the case state."""
    if state.human_approval_status == "PENDING":
        return "PENDING_REVIEW"
    if state.human_approval_status == "REJECTED":
        return "REJECTED"
    if state.refund_executed:
        return "REFUND_ISSUED"
    if state.refund_package is not None:
        return "REFUND_PREPARED"
    return "RESOLVED"


def upsert(case_id: str, *, state, run_kwargs: dict[str, Any],
           customer_name: str, issue: str) -> None:
    existing = CASES.get(case_id, {})
    CASES[case_id] = {
        "case_id": case_id,
        "state": state,
        "run_kwargs": run_kwargs,
        "customer_name": customer_name,
        "issue": issue,
        "status": status_of(state),
        "sla_status": state.sla_status,
        "next_update_at": state.next_update_at,
        "sla_due_at": state.sla_due_at,
        "created_at": existing.get("created_at", _now()),
        "updated_at": _now(),
    }


def get(case_id: str) -> dict[str, Any] | None:
    return CASES.get(case_id)


def all_cases() -> list[dict[str, Any]]:
    return sorted(CASES.values(), key=lambda c: c["created_at"], reverse=True)


def pending() -> list[dict[str, Any]]:
    return [c for c in all_cases() if c["status"] == "PENDING_REVIEW"]


def reset() -> None:
    CASES.clear()
