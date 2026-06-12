"""Deterministic fraud-risk engine with named fraud typologies.

No randomness, no LLM: identical evidence always yields the identical score and
the identical fraud pattern, so the audit trail is fully reproducible. Signals
are additive weights capped at 100. A score >= the policy threshold routes the
case to a human.

The engine never tells the CUSTOMER they are a fraudster (their notice always
says "additional verification is required"). Internally, for the STAFF console,
it produces a valuable, evidence-backed assessment: each signal carries the
actual evidence that fired it, the case is classified into a recognised fraud
typology (e.g. Account-Takeover refund abuse), and a concrete mitigation is
recommended.
"""
from __future__ import annotations

from typing import Any

from .state import Evidence, RiskSignal

# code, description, weight. Tuned so the Scenario A account-takeover pattern
# saturates well above the 70 human-review threshold, while a clean billing
# query scores 0.
SIGNAL_DEFS = [
    ("DELIVERY_CONFIRMED", "Carrier confirmed delivery with proof of delivery.", 25),
    ("RECENT_ACCOUNT_CHANGE", "Account contact details changed shortly before the dispute.", 25),
    ("PREVIOUS_REFUND_ISSUED", "A goodwill credit/refund was already issued to this account.", 20),
    ("MULTIPLE_REFUND_ATTEMPTS", "Multiple refund attempts on this account in the last 90 days.", 20),
    ("IDENTITY_VERIFICATION_FAILURE", "Identity verification failed or could not be completed.", 25),
    ("HIGH_VALUE_ORDER", "Disputed amount is high value, raising the stakes of an abusive refund.", 10),
    ("DELIVERY_ADDRESS_MISMATCH", "Delivery location does not match the registered address.", 15),
    ("PHONE_NOT_VERIFIED", "The account's phone number is not verified.", 10),
]

RISK_THRESHOLD = 70
HIGH_VALUE_AED = 2000


def _recent_account_change(customer: dict[str, Any]) -> bool:
    return bool(customer.get("email_changed_at"))


def _evidence_text(code: str, evidence: Evidence, customer: dict[str, Any],
                   identity_verified: bool) -> str:
    """The concrete fact behind a fired signal (shown to the reviewer)."""
    order = evidence.order or {}
    shipment = evidence.shipment or {}
    if code == "DELIVERY_CONFIRMED":
        return (f"Delivered {shipment.get('delivered_at','?')}; "
                f"proof: {shipment.get('proof_of_delivery','on file')}.")
    if code == "RECENT_ACCOUNT_CHANGE":
        return f"Email changed at {customer.get('email_changed_at')}, shortly before this dispute."
    if code == "PREVIOUS_REFUND_ISSUED":
        return f"Goodwill credit already issued on {customer.get('previous_goodwill_credit_at','a prior date')}."
    if code == "MULTIPLE_REFUND_ATTEMPTS":
        return f"{customer.get('refund_attempts_last_90d',0)} refund attempts in the last 90 days."
    if code == "IDENTITY_VERIFICATION_FAILURE":
        return "Emirates ID / OTP verification did not pass."
    if code == "HIGH_VALUE_ORDER":
        return f"Order value {order.get('currency','AED')} {order.get('amount',0):,.2f} (threshold {HIGH_VALUE_AED})."
    if code == "DELIVERY_ADDRESS_MISMATCH":
        return f"Delivery geo: {shipment.get('delivery_geo','unknown')}."
    if code == "PHONE_NOT_VERIFIED":
        return "registered_phone is flagged unverified on the account."
    return ""


def _classify(fired: set[str], issue_type: str, score: int) -> tuple[str, str]:
    """Return (typology, recommended_mitigation)."""
    ato = {"RECENT_ACCOUNT_CHANGE"} <= fired and (
        {"PREVIOUS_REFUND_ISSUED"} <= fired or {"MULTIPLE_REFUND_ATTEMPTS"} <= fired)
    if ato and "DELIVERY_CONFIRMED" in fired:
        return ("Account-Takeover / serial refund abuse",
                "Pause refund. Require step-up identity re-verification and manual "
                "review of the account-change and refund history before any payout.")
    if "IDENTITY_VERIFICATION_FAILURE" in fired:
        return ("Identity verification failure",
                "Do not proceed. Re-run Emirates ID + OTP verification; route to a human.")
    if "DELIVERY_CONFIRMED" in fired and "RECENT_ACCOUNT_CHANGE" not in fired:
        return ("First-party (friendly) fraud risk: item-not-received on a confirmed delivery",
                "Hold refund for human review; compare proof-of-delivery against the claim.")
    if "DELIVERY_ADDRESS_MISMATCH" in fired:
        return ("Possible misdelivery or address manipulation",
                "Verify the delivery address with the customer before any remedy.")
    if score == 0:
        return ("No fraud indicators (billing confusion)",
                "Safe to resolve per policy; no elevated review needed.")
    return ("Low-level anomaly", "Proceed per policy; monitor the account.")


def band(score: int) -> str:
    if score >= RISK_THRESHOLD:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def compute_risk(issue_type: str, evidence: Evidence, identity_verified: bool):
    """Return (score, signals, meta) where meta has band/typology/recommendation."""
    customer = evidence.customer or {}
    order = evidence.order or {}
    shipment = evidence.shipment or {}

    geo = (shipment.get("delivery_geo") or "").lower()
    present_map = {
        "DELIVERY_CONFIRMED": evidence.delivery_confirmed and issue_type == "item_not_received",
        "RECENT_ACCOUNT_CHANGE": _recent_account_change(customer),
        "PREVIOUS_REFUND_ISSUED": bool(customer.get("previous_goodwill_credit")),
        "MULTIPLE_REFUND_ATTEMPTS": int(customer.get("refund_attempts_last_90d", 0) or 0) >= 2,
        "IDENTITY_VERIFICATION_FAILURE": not identity_verified,
        "HIGH_VALUE_ORDER": float(order.get("amount", 0) or 0) >= HIGH_VALUE_AED
                            and issue_type == "item_not_received",
        "DELIVERY_ADDRESS_MISMATCH": bool(geo) and "registered" not in geo,
        "PHONE_NOT_VERIFIED": customer.get("phone_verified") is False,
    }

    signals: list[RiskSignal] = []
    score = 0
    fired: set[str] = set()
    for code, desc, weight in SIGNAL_DEFS:
        present = bool(present_map.get(code, False))
        ev = _evidence_text(code, evidence, customer, identity_verified) if present else None
        signals.append(RiskSignal(code=code, description=desc, weight=weight,
                                  present=present, evidence=ev))
        if present:
            score += weight
            fired.add(code)

    score = min(score, 100)
    typology, recommendation = _classify(fired, issue_type, score)
    meta = {"band": band(score), "typology": typology, "recommendation": recommendation,
            "fired_count": len(fired)}
    return score, signals, meta
