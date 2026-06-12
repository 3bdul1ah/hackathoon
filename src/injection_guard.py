"""Prompt-injection / policy-override defense.

The customer message is untrusted input. If it tries to override policy,
escalate privileges, or command an immediate refund, we:
  1. detect it deterministically,
  2. flag it for the audit log as PROMPT_INJECTION_ATTEMPT,
  3. continue the normal workflow unchanged (the attempt has zero effect on
     policy, risk scoring, or the refund gate).
"""
from __future__ import annotations

import re

PATTERNS = [
    r"ignore (the |all |previous )?(policy|policies|rules|instructions)",
    r"override (the )?policy",
    r"refund me (now|immediately|right now)",
    r"just (refund|approve)( me)?",
    r"you (must|have to|are required to) refund",
    r"bypass (the )?(review|approval|verification|policy)",
    r"forget (your|the) (instructions|rules|policy)",
    r"act as (an )?admin",
    r"disregard (the )?(policy|rules|guidelines)",
    r"do not (route|escalate|verify)",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in PATTERNS]


def scan(message: str) -> tuple[bool, str | None]:
    """Return (detected, matched_phrase)."""
    if not message:
        return False, None
    for rx in _COMPILED:
        m = rx.search(message)
        if m:
            return True, m.group(0)
    return False, None
