"""Versioned, file-driven policy engine.

Rules live in policy/policy_v1.json so policy is data, not code, and the version
is cited in every decision. Rules are evaluated top-to-bottom; the first whose
conditions all match wins. R-000 (empty conditions) is the safe fallback.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .state import Evidence, PolicyDecision

POLICY_PATH = Path(__file__).resolve().parent.parent / "policy" / "policy_v1.json"


def load_policy() -> dict[str, Any]:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _facts(issue_type: str, evidence: Evidence, risk_score: int) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "delivery_confirmed": evidence.delivery_confirmed,
        "duplicate_charge_confirmed": evidence.duplicate_charge_confirmed,
        "authorization_hold_present": evidence.authorization_hold_present,
        "risk_score": risk_score,
    }


def _matches(conditions: dict[str, Any], facts: dict[str, Any]) -> bool:
    for key, expected in conditions.items():
        if key.endswith("_gte"):
            if not facts.get(key[:-4], 0) >= expected:
                return False
        elif key.endswith("_lt"):
            if not facts.get(key[:-3], 0) < expected:
                return False
        else:
            if facts.get(key) != expected:
                return False
    return True


def evaluate(issue_type: str, evidence: Evidence, risk_score: int) -> PolicyDecision:
    policy = load_policy()
    facts = _facts(issue_type, evidence, risk_score)

    for rule in policy["rules"]:
        if _matches(rule["conditions"], facts):
            out = rule["outcome"]
            return PolicyDecision(
                policy_version=policy["policy_version"],
                rule_id=rule["rule_id"],
                refund_allowed=out["refund_allowed"],
                requires_human_review=out["requires_human_review"],
                action=out["action"],
                reason=out["reason"],
                legal_refs=rule.get("legal_refs", []),
            )

    # Should never reach here because R-000 has empty conditions, but be safe.
    return PolicyDecision(
        policy_version=policy["policy_version"],
        rule_id="R-000",
        refund_allowed=False,
        requires_human_review=True,
        action="ROUTE_TO_HUMAN_REVIEW",
        reason="No matching rule; routed to human review as a safe default.",
    )
