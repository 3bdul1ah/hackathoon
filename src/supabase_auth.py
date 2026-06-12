"""Supabase email OTP helpers for the Streamlit login step.

The app uses Supabase to send and verify a real email OTP when the project is
configured with `SUPABASE_URL` and `SUPABASE_KEY` (or `SUPABASE_ANON_KEY`).
If those values are missing, the helper returns a local demo code so the UI can
still be exercised without a live Supabase project.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import os
import secrets


@dataclass(frozen=True)
class EmailOtpSendResult:
    delivered: bool
    message: str
    demo_code: str | None = None


def _supabase_client() -> tuple[Any | None, str | None]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return None, (
            "Set SUPABASE_URL and SUPABASE_KEY to enable real email OTPs. "
            "Until then, the app can use a local demo code."
        )

    try:
        from supabase import create_client
    except Exception as exc:  # pragma: no cover - dependency/config error path
        return None, (
            "Install the `supabase` package to enable real email OTPs: "
            f"{exc}"
        )

    try:
        return create_client(url, key), None
    except Exception as exc:  # pragma: no cover - config error path
        return None, f"Could not initialize the Supabase client: {exc}"


def _demo_fallback_allowed(error: str | None) -> bool:
    return bool(error and (
        error.startswith("Set SUPABASE_URL and SUPABASE_KEY")
        or error.startswith("Install the `supabase` package")
    ))


def request_email_otp(email: str) -> EmailOtpSendResult:
    """Send an email OTP or return a demo code if Supabase is unavailable."""
    normalized_email = email.strip()
    client, error = _supabase_client()
    if client is None:
        if not _demo_fallback_allowed(error):
            return EmailOtpSendResult(
                delivered=False,
                message=error or "Supabase is unavailable.",
            )
        return EmailOtpSendResult(
            delivered=False,
            message=error or "Supabase is unavailable.",
            demo_code=f"{secrets.randbelow(1_000_000):06d}",
        )

    try:
        client.auth.sign_in_with_otp({"email": normalized_email})
    except Exception as exc:  # pragma: no cover - runtime Supabase error path
        return EmailOtpSendResult(
            delivered=False,
            message=f"Supabase could not send the email OTP: {exc}",
        )

    return EmailOtpSendResult(
        delivered=True,
        message=f"Sent a Supabase email OTP to {normalized_email}.",
    )


def verify_email_otp(email: str, token: str) -> tuple[bool, str]:
    """Verify an email OTP through Supabase."""
    normalized_email = email.strip()
    normalized_token = token.strip()
    client, error = _supabase_client()
    if client is None:
        return False, error or "Supabase is unavailable."

    try:
        client.auth.verify_otp({
            "email": normalized_email,
            "token": normalized_token,
            "type": "email",
        })
    except Exception as exc:  # pragma: no cover - runtime Supabase error path
        return False, f"Supabase rejected the email OTP: {exc}"

    return True, f"Verified the email OTP for {normalized_email}."
