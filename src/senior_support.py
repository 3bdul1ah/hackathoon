"""Senior-safe support helpers.

This module keeps vulnerable-customer protection deterministic and auditable.
It does not decide refunds. It identifies when a senior or caregiver-assisted
case needs extra care, clearer communication, or human review.
"""
from __future__ import annotations

from typing import Any


PRESSURE_PATTERNS = {
    "OTP_OR_CODE_REQUEST": (
        "otp",
        "one time code",
        "verification code",
        "share the code",
        "send the code",
        "رمز التحقق",
        "رمز الدخول",
        "الرمز",
        "شارك الرمز",
        "ارسل الرمز",
        "أرسل الرمز",
        "otp",
    ),
    "URGENT_PAYMENT_PRESSURE": (
        "urgent transfer",
        "pay immediately",
        "right now",
        "before it expires",
        "account will be blocked",
        "police case",
        "ادفع الآن",
        "ادفع فورا",
        "تحويل عاجل",
        "قبل انتهاء",
        "سيتم حظر الحساب",
        "سيغلق حسابي",
        "سيتم اغلاق الحساب",
        "قضية شرطة",
    ),
    "SUSPICIOUS_PAYMENT_METHOD": (
        "gift card",
        "crypto",
        "bitcoin",
        "payment link",
        "bank transfer",
        "wire transfer",
        "بطاقة هدايا",
        "عملات رقمية",
        "بتكوين",
        "بيتكوين",
        "رابط دفع",
        "تحويل بنكي",
        "حوالة بنكية",
    ),
    "THIRD_PARTY_INSTRUCTION": (
        "someone called",
        "caller told me",
        "they told me",
        "whatsapp message",
        "sms link",
        "support agent told me",
        "اتصل بي شخص",
        "شخص اتصل بي",
        "المتصل قال",
        "قالوا لي",
        "رسالة واتساب",
        "واتساب",
        "رابط sms",
        "رسالة نصية",
        "موظف الدعم قال",
    ),
    "REMOTE_ACCESS_PRESSURE": (
        "anydesk",
        "teamviewer",
        "remote access",
        "screen share",
        "control my phone",
        "اني ديسك",
        "تيم فيور",
        "وصول عن بعد",
        "مشاركة الشاشة",
        "التحكم في هاتفي",
        "يسيطر على هاتفي",
    ),
}


def analyze_message(message: str, *, senior_mode_enabled: bool,
                    is_senior: bool, caregiver_authorized: bool) -> dict[str, Any]:
    """Return senior-protection flags and a reviewer-facing summary."""
    if not senior_mode_enabled and not is_senior:
        return {"flags": [], "summary": None}

    msg = message.lower()
    flags: list[str] = []
    for code, phrases in PRESSURE_PATTERNS.items():
        if any(phrase in msg for phrase in phrases):
            flags.append(code)

    context: list[str] = []
    if is_senior:
        context.append("senior customer")
    if caregiver_authorized:
        context.append("trusted caregiver authorized")
    if senior_mode_enabled:
        context.append("senior-safe communication requested")

    if flags:
        summary = (
            "Potential scam or coercion targeting a senior: "
            + ", ".join(flags).replace("_", " ").lower()
            + ". Route to a human reviewer for protective verification."
        )
    elif context:
        summary = "Senior-safe support context: " + ", ".join(context) + "."
    else:
        summary = None

    return {"flags": flags, "summary": summary}
