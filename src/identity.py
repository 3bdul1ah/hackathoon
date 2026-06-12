"""Emirates ID based identity verification (mocked, multi-factor).

This runs BEFORE the dispute is processed: a customer must prove who they are
with their Emirates ID and a one-time passcode before the agent will look at any
order or payment. The agent never sees real KYC data here; all checks are mocked
against the customer record, but the *flow* mirrors a real step-up KYC: format
check, identity match, OTP.

The result feeds the fraud engine (a failed check raises risk) and the audit
trail (every factor is logged), and it is shown to the human reviewer so a
person, not the agent alone, owns the final money decision.
"""
from __future__ import annotations

import re
from typing import Any

# UAE Emirates ID format: 784-YYYY-NNNNNNN-N
EID_RE = re.compile(r"^784-\d{4}-\d{7}-\d$")


def valid_eid_format(eid: str | None) -> bool:
    return bool(eid and EID_RE.match(eid.strip()))


def verify(customer: dict[str, Any] | None, *, provided_emirates_id: str | None,
           otp_verified: bool) -> dict[str, Any]:
    """Return a structured verification result.

    factors: each named check with pass/fail. `verified` is True only when the
    Emirates ID format is valid, it matches the account on file, and the OTP
    check passed.
    """
    customer = customer or {}
    on_file = customer.get("emirates_id")

    fmt_ok = valid_eid_format(provided_emirates_id)
    match_ok = bool(provided_emirates_id and on_file
                    and provided_emirates_id.strip() == on_file)
    email_recently_changed = bool(customer.get("email_changed_at"))

    factors = [
        {"factor": "Emirates ID format (784-YYYY-NNNNNNN-N)", "passed": fmt_ok},
        {"factor": "Emirates ID matches account on file", "passed": match_ok},
        {"factor": "One-time passcode (OTP) to registered phone", "passed": bool(otp_verified)},
    ]

    verified = fmt_ok and match_ok and bool(otp_verified)

    if not verified:
        detail = "Identity NOT verified: " + ", ".join(
            f["factor"] for f in factors if not f["passed"]) + " failed."
    elif email_recently_changed:
        detail = ("Identity verified via Emirates ID + OTP. Note: a recent email "
                  "change is flagged for the reviewer.")
    else:
        detail = "Identity verified via Emirates ID + OTP."

    return {
        "verified": verified,
        "factors": factors,
        "email_recently_changed": email_recently_changed,
        "detail": detail,
    }
