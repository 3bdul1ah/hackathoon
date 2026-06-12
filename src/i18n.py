"""Small bilingual helpers for customer-facing Arabic and English support."""
from __future__ import annotations

import re
from typing import Literal

Language = Literal["en", "ar"]

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")


def detect_language(text: str | None) -> Language:
    """Detect the customer language deterministically.

    Arabic script in the customer message wins. Empty, numeric, or neutral text
    defaults to English so existing demos keep their current behavior.
    """
    if text and _ARABIC_RE.search(text):
        return "ar"
    return "en"


def dir_for(language: str | None) -> str:
    return "rtl" if language == "ar" else "ltr"


def language_name(language: str | None) -> str:
    return "Arabic" if language == "ar" else "English"


_TEXT: dict[str, dict[Language, str]] = {
    "yes": {"en": "Yes", "ar": "نعم"},
    "no": {"en": "No", "ar": "لا"},
    "not_scheduled": {"en": "not scheduled", "ar": "غير مجدول"},
    "available": {"en": "Available", "ar": "متاح"},
    "not_needed": {"en": "Not needed right now", "ar": "غير مطلوب الآن"},
    "status_on_track": {"en": "on track", "ar": "ضمن المسار"},
    "status_due_soon": {"en": "due soon", "ar": "يستحق قريباً"},
    "status_overdue": {"en": "overdue", "ar": "متأخر"},
    "status_closed": {"en": "closed", "ar": "مغلق"},
    "owner": {"en": "Owner", "ar": "المسؤول"},
    "next_update_by": {"en": "Next update by", "ar": "التحديث القادم قبل"},
    "sla_due": {"en": "SLA due", "ar": "الموعد النهائي"},
    "status": {"en": "Status", "ar": "الحالة"},
    "appeal_path": {"en": "Appeal path", "ar": "مسار الاعتراض"},
    "status_assurance": {"en": "Status assurance", "ar": "تأكيد حالة الطلب"},
    "follow_up_log": {"en": "Follow-up action log:", "ar": "سجل إجراءات المتابعة:"},
    "senior_safe_mode": {"en": "Senior-safe mode", "ar": "وضع حماية كبار السن"},
    "senior_customer": {"en": "Senior customer", "ar": "عميل من كبار السن"},
    "detected_language": {"en": "Detected language", "ar": "اللغة المكتشفة"},
    "caregiver_updates": {"en": "Caregiver updates", "ar": "تحديثات مقدم الرعاية"},
    "enabled": {"en": "Enabled", "ar": "مفعل"},
    "not_requested": {"en": "Not requested", "ar": "غير مطلوب"},
    "not_declared": {"en": "Not declared", "ar": "غير مصرح به"},
    "authorized": {"en": "Authorized", "ar": "مصرح به"},
    "not_authorized": {"en": "Not authorized", "ar": "غير مصرح به"},
    "caregiver": {"en": "Caregiver", "ar": "مقدم الرعاية"},
    "relationship": {"en": "Relationship", "ar": "صلة القرابة"},
    "caregiver_phone": {"en": "Caregiver phone", "ar": "هاتف مقدم الرعاية"},
    "not_provided": {"en": "not provided", "ar": "غير متوفر"},
    "protection_flags": {"en": "Protection flags", "ar": "مؤشرات الحماية"},
    "senior_safe_support": {"en": "Senior-safe support", "ar": "دعم آمن لكبار السن"},
    "you": {"en": "You", "ar": "أنت"},
    "support_assistant": {"en": "Support assistant", "ar": "مساعد الدعم"},
    "reply_unavailable_title": {"en": "Reply could not be generated", "ar": "تعذر إنشاء الرد"},
    "reply_unavailable_body": {
        "en": "The OpenAI API is not reachable yet, so the worded reply is unavailable. The decision below is still fully computed. Add a valid OpenAI key (OPENAI_API_KEY=sk-...) to .env to see the friendly message.",
        "ar": "واجهة OpenAI غير متاحة حالياً، لذلك لا يمكن عرض الصياغة النهائية. القرار أدناه محسوب بالكامل. أضف مفتاح OpenAI صالحاً في ملف .env لعرض الرسالة الودية.",
    },
    "pending_title": {"en": "We are taking a closer look", "ar": "نراجع طلبك بعناية"},
    "pending_body": {
        "en": "To protect your account, one of our specialists is reviewing your request. You do not need to do anything. We will follow up shortly.",
        "ar": "لحماية حسابك، يراجع أحد المختصين طلبك. لا تحتاج إلى اتخاذ أي إجراء الآن. سنتابع معك قريباً.",
    },
    "rejected_title": {"en": "We could not approve this request", "ar": "لم نتمكن من الموافقة على هذا الطلب"},
    "rejected_body": {
        "en": "After a careful review we were unable to approve a refund for this case. If you have more information, please reply and we will take another look.",
        "ar": "بعد مراجعة دقيقة، لم نتمكن من الموافقة على استرداد المبلغ لهذه الحالة. إذا كانت لديك معلومات إضافية، أرسلها لنا وسنراجع الطلب مرة أخرى.",
    },
    "refund_executed_title": {"en": "Your refund is on its way", "ar": "المبلغ المسترد في طريقه إليك"},
    "refund_executed_body": {
        "en": "A refund of <b>{amount}</b> has been approved and issued to your original payment method.",
        "ar": "تمت الموافقة على استرداد مبلغ <b>{amount}</b> وإرساله إلى طريقة الدفع الأصلية.",
    },
    "refund_prepared_title": {"en": "Your refund has been approved", "ar": "تمت الموافقة على استرداد المبلغ"},
    "refund_prepared_body": {
        "en": "A refund of <b>{amount}</b> has been prepared and will be issued to your original payment method.",
        "ar": "تم تجهيز استرداد مبلغ <b>{amount}</b> وسيتم إرساله إلى طريقة الدفع الأصلية.",
    },
    "no_refund_title": {"en": "Here is what we found", "ar": "هذا ما وجدناه"},
    "no_refund_body": {
        "en": "Good news. There is nothing to refund. See the explanation above.",
        "ar": "الخبر الجيد أنه لا يوجد مبلغ يحتاج إلى استرداد. راجع التوضيح أعلاه.",
    },
    "page_title": {"en": "Help Center: Payments and Refunds", "ar": "مركز المساعدة: المدفوعات والاسترداد"},
    "page_sub": {
        "en": "Confirm it is really you, tell us what went wrong, and our assistant will look into it. A person signs off before any money moves.",
        "ar": "أكد هويتك، وأخبرنا بما حدث، وسيتحقق المساعد من طلبك. لا يتم نقل أي مبلغ قبل موافقة شخص مختص.",
    },
    "page_caption": {
        "en": "Built for UAE residents who need clear refund timelines, especially for high-cost flights, electronics, telecom, utilities, and marketplace purchases.",
        "ar": "مصمم لسكان دولة الإمارات الذين يحتاجون إلى مواعيد واضحة للاسترداد، خصوصاً في الرحلات والإلكترونيات والاتصالات والمرافق ومشتريات الأسواق الإلكترونية.",
    },
    "verify_step_title": {"en": "Step 1: Verify your identity", "ar": "الخطوة 1: تحقق من هويتك"},
    "verify_step_body": {
        "en": "Before we look at any order or payment, please confirm who you are. This is a mocked UAE PASS / Emirates ID step.",
        "ar": "قبل مراجعة أي طلب أو دفعة، يرجى تأكيد هويتك. هذه خطوة تجريبية تحاكي UAE PASS / الهوية الإماراتية.",
    },
    "eid_label": {"en": "Emirates ID (784-YYYY-NNNNNNN-N)", "ar": "الهوية الإماراتية (784-YYYY-NNNNNNN-N)"},
    "send_otp": {"en": "Send OTP", "ar": "إرسال رمز التحقق"},
    "eid_not_recognized_title": {"en": "Emirates ID not recognized", "ar": "لم يتم التعرف على الهوية الإماراتية"},
    "eid_not_recognized_body": {"en": "We could not find an account for that Emirates ID.", "ar": "لم نجد حساباً مرتبطاً بهذه الهوية الإماراتية."},
    "mock_sms": {"en": "Mock SMS to {phone} . demo code <b>{otp}</b>", "ar": "رسالة تجريبية إلى {phone} . رمز العرض <b>{otp}</b>"},
    "otp_label": {"en": "Enter the 6-digit code", "ar": "أدخل الرمز المكون من 6 أرقام"},
    "verify_identity": {"en": "Verify identity", "ar": "تحقق من الهوية"},
    "could_not_verify_title": {"en": "Could not verify", "ar": "تعذر التحقق"},
    "could_not_verify_body": {"en": "That Emirates ID does not match any account or is malformed.", "ar": "هذه الهوية الإماراتية غير مرتبطة بأي حساب أو أن تنسيقها غير صحيح."},
    "incorrect_code_title": {"en": "Incorrect code", "ar": "الرمز غير صحيح"},
    "incorrect_code_body": {"en": "Tap Send OTP and use the demo code shown.", "ar": "اضغط إرسال رمز التحقق واستخدم رمز العرض الظاهر."},
    "identity_verified_title": {"en": "Identity verified", "ar": "تم التحقق من الهوية"},
    "identity_verified_body": {"en": "Welcome back, <b>{name}</b>. How can we help you today?", "ar": "مرحباً بعودتك، <b>{name}</b>. كيف يمكننا مساعدتك اليوم؟"},
    "switch_identity": {"en": "Not you? Switch identity", "ar": "لست أنت؟ تغيير الهوية"},
    "senior_optional_title": {"en": "Optional: senior-safe support", "ar": "اختياري: دعم آمن لكبار السن"},
    "senior_optional_body": {
        "en": "Use this if you are a senior citizen or helping an older family member. It makes the case easier to follow and lets us protect against scam pressure.",
        "ar": "استخدم هذا الخيار إذا كنت من كبار السن أو تساعد فرداً أكبر سناً من العائلة. يجعل الحالة أسهل في المتابعة ويساعدنا على الحماية من ضغط الاحتيال.",
    },
    "senior_checkbox": {"en": "I am a senior citizen / helping a senior", "ar": "أنا من كبار السن / أساعد شخصاً من كبار السن"},
    "senior_mode_checkbox": {"en": "Use simpler explanations and extra account protection", "ar": "استخدام شرح أبسط وحماية إضافية للحساب"},
    "caregiver_checkbox": {
        "en": "Authorize a trusted caregiver or family member to receive case updates",
        "ar": "تفويض مقدم رعاية أو فرد موثوق من العائلة لتلقي تحديثات الحالة",
    },
    "caregiver_name": {"en": "Caregiver name", "ar": "اسم مقدم الرعاية"},
    "message_prompt": {"en": "Tell us what happened, in your own words:", "ar": "أخبرنا بما حدث بكلماتك:"},
    "placeholder_senior": {
        "en": "Example: Someone called me and sent a payment link, saying my account will be blocked unless I pay now.",
        "ar": "مثال: اتصل بي شخص وأرسل رابط دفع وقال إن حسابي سيغلق إذا لم أدفع الآن.",
    },
    "placeholder_default": {"en": "Type your issue here.", "ar": "اكتب مشكلتك هنا."},
    "submit_request": {"en": "Submit request", "ar": "إرسال الطلب"},
    "pending_caption": {"en": "Your request is with our review team. This page updates when they decide.", "ar": "طلبك لدى فريق المراجعة. سيتم تحديث هذه الصفحة عند صدور القرار."},
    "refresh_status": {"en": "Refresh status", "ar": "تحديث الحالة"},
    "rights_prefix": {"en": "Your rights:", "ar": "حقوقك:"},
    "rights_body": {"en": "this outcome is grounded in the {source}. {basis}", "ar": "هذه النتيجة مستندة إلى {source}. {basis}"},
    "progress": {"en": "Progress", "ar": "التقدم"},
    "reference": {"en": "Reference: {case_id}", "ar": "المرجع: {case_id}"},
    "step_triage": {"en": "Understanding your request", "ar": "فهم طلبك"},
    "step_identity": {"en": "Confirming your identity", "ar": "تأكيد هويتك"},
    "step_evidence": {"en": "Looking up your order and payments", "ar": "البحث عن طلبك ومدفوعاتك"},
    "step_senior": {"en": "Checking senior-safe support needs", "ar": "التحقق من احتياجات دعم كبار السن"},
    "step_fraud": {"en": "Running a quick security check", "ar": "إجراء فحص أمني سريع"},
    "step_policy": {"en": "Applying our refund policy", "ar": "تطبيق سياسة الاسترداد"},
    "step_legal": {"en": "Checking UAE Consumer Protection Law", "ar": "التحقق من قانون حماية المستهلك الإماراتي"},
    "step_decision": {"en": "Reaching a decision", "ar": "الوصول إلى قرار"},
    "step_human": {"en": "Human reviewer sign-off", "ar": "موافقة المراجع المختص"},
    "step_prepare": {"en": "Preparing your resolution", "ar": "تجهيز الحل"},
    "step_execute": {"en": "Issuing your refund", "ar": "إصدار الاسترداد"},
    "step_audit": {"en": "Wrapping up", "ar": "إنهاء الحالة"},
    "speech_future": {
        "en": "Speech input will use the browser language for the detected case language: {speech_lang}.",
        "ar": "سيستخدم إدخال الصوت لغة المتصفح المناسبة للغة الحالة المكتشفة: {speech_lang}.",
    },
}


def t(key: str, language: str | None = "en", **kwargs: object) -> str:
    lang: Language = "ar" if language == "ar" else "en"
    value = _TEXT.get(key, {}).get(lang) or _TEXT.get(key, {}).get("en") or key
    return value.format(**kwargs) if kwargs else value
