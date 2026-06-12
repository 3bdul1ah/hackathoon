"""Deterministic status assurance for customer-facing dispute cases.

This is intentionally small and local: it does not send messages or integrate
with calendars, CRMs, or payment rails. It computes the promises the UI can show
so customers know who owns the case, when they will hear back, and how to appeal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sla_status(due_at: str | None, now: datetime, closed: bool) -> str:
    if closed:
        return "closed"
    due = _parse_iso(due_at)
    if due is None:
        return "on_track"
    if now >= due:
        return "overdue"
    if due - now <= timedelta(minutes=30):
        return "due_soon"
    return "on_track"


def _auth_hold_release_at(state) -> str | None:
    for payment in state.evidence.payments:
        if payment.get("status") == "authorization_hold":
            return payment.get("auth_expires_at")
    return None


def _base_event(kind: str, message: str, when: str) -> dict[str, Any]:
    return {"type": kind, "scheduled_at": when, "message": message}


def compute_status_assurance(state, *, now: datetime | None = None) -> dict[str, Any]:
    """Return status fields to merge into ``CaseState``.

    The values are deterministic from the final case state and current time.
    They are deliberately human-readable because the same values appear in the
    customer page, staff queue, audit trail, and scenario JSON.
    """
    now = now or _now()
    closed = state.human_approval_status in {"REJECTED", "NOT_REQUIRED"} or state.refund_executed

    if state.human_approval_status == "PENDING":
        next_update = now + timedelta(minutes=30)
        sla_due = now + timedelta(hours=4)
        owner = "Senior protection specialist" if state.senior_protection_flags else "Risk review specialist"
        if state.senior_protection_flags:
            message = (
                "A specialist owns this protective review. We will not follow urgent "
                "third-party payment instructions, and you will receive an update within "
                "30 minutes."
            )
        else:
            message = (
                "A specialist owns this review. You will receive an update within "
                "30 minutes, even if the final decision needs more time."
            )
        appeal = False
        events = [
            _base_event("next_update", "Send customer a review status update.", _iso(next_update)),
            _base_event("sla_due", "Escalate if the review is not decided.", _iso(sla_due)),
        ]
        if state.caregiver_authorized:
            events.append(_base_event(
                "caregiver_update",
                f"Share status with authorized caregiver {state.caregiver_name or ''}.".strip(),
                _iso(next_update),
            ))
    elif state.refund_executed:
        next_update = now + timedelta(hours=24)
        sla_due = now + timedelta(days=3)
        owner = "Payments operations"
        message = (
            "Your refund was approved and issued to the original payment method. "
            "We will check the refund trace within 24 hours and keep the case "
            "open until the payment rail confirms it."
        )
        appeal = False
        events = [
            _base_event("refund_trace_check", "Confirm refund trace status with payments ops.", _iso(next_update)),
            _base_event("refund_eta", "Expected refund arrival window for the customer.", _iso(sla_due)),
        ]
    elif state.human_approval_status == "REJECTED":
        next_update = now + timedelta(hours=24)
        sla_due = now + timedelta(days=2)
        owner = "Customer care escalation desk"
        message = (
            "The review is closed, but you can submit new evidence or ask for a "
            "second look. The escalation desk will acknowledge an appeal within "
            "24 hours."
        )
        appeal = True
        events = [
            _base_event("appeal_window", "Customer may submit new evidence for a second look.", _iso(sla_due)),
        ]
    elif state.policy_decision and state.policy_decision.rule_id == "R-004":
        release_at = _auth_hold_release_at(state)
        parsed_release = _parse_iso(release_at)
        next_update = parsed_release or (now + timedelta(days=3))
        sla_due = next_update
        owner = "Payments support automation"
        message = (
            "There is one settled charge and one temporary authorization hold. "
            "The hold is expected to release automatically by the date shown, "
            "and you can reopen the case if it still appears after that."
        )
        appeal = True
        events = [
            _base_event("auth_hold_release_check", "Check whether the bank authorization hold has released.", _iso(next_update)),
        ]
    else:
        next_update = now + timedelta(hours=24)
        sla_due = now + timedelta(hours=24)
        owner = "Customer care"
        message = (
            "This case is resolved. If anything still looks wrong, reply with "
            "new evidence and the team will reopen the review path."
        )
        appeal = True
        events = [
            _base_event("reopen_available", "Customer may reopen with new evidence.", _iso(next_update)),
        ]

    if state.senior_mode_enabled and state.caregiver_authorized:
        message += (
            f" Updates may also be shared with the authorized caregiver"
            f"{' ' + state.caregiver_name if state.caregiver_name else ''}."
        )
    elif state.senior_mode_enabled:
        message += " Senior-safe explanations are enabled for this case."

    return {
        "sla_due_at": _iso(sla_due),
        "next_update_at": _iso(next_update),
        "assigned_owner": owner,
        "customer_waiting_message": message,
        "appeal_available": appeal,
        "follow_up_events": events,
        "sla_status": _sla_status(_iso(sla_due), now, closed),
    }
