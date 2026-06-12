"""Customer-facing notice generation, powered by the OpenAI API.

The customer reply is ALWAYS generated online by OpenAI using the key in `.env`
(OPENAI_API_KEY, optional OPENAI_MODEL). There is no offline template fallback:
if the API is unreachable or the key is invalid, we surface a clear error notice
instead of inventing text.

The agent's DECISION (refund approved / under review / no refund) is computed by
the deterministic fraud + policy engines and passed to the model as grounding so
the wording can never contradict the decision, the amount, or the policy. The
customer is never accused of fraud; elevated risk is phrased as "additional
verification is required". The model is also instructed not to use any dashes.
"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _decision_brief(action: str, *, amount: float | None, currency: str) -> str:
    """Factual grounding handed to the model. Not shown to the customer as-is."""
    if action == "ROUTE_TO_HUMAN_REVIEW":
        return ("Decision: the request needs ADDITIONAL VERIFICATION and is under "
                "review by a human specialist. Do NOT promise a refund. Do NOT "
                "accuse the customer of anything. Tell them nothing is required "
                "from them right now and that we will follow up shortly.")
    if action == "PREPARE_REFUND":
        amt = f"{currency} {amount:,.2f}" if amount is not None else "the disputed amount"
        return (f"Decision: a refund of {amt} has been APPROVED and prepared to the "
                "customer's original payment method. Confirm this warmly.")
    if action == "EXPLAIN_NO_REFUND":
        return ("Decision: NO refund is owed. There is only one real charge on the "
                "order; the second entry the customer saw is a temporary "
                "authorization hold placed by their bank at checkout, which is not "
                "a separate charge and will be released automatically within a few "
                "days. Reassure them and explain this clearly.")
    return "Decision: the request has been received and is being processed."


def _client_and_model():
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return None, model, "OPENAI_API_KEY is not set in .env"
    from openai import OpenAI
    return OpenAI(api_key=api_key), model, None


def generate_notice(action: str, *, amount: float | None = None,
                    currency: str = "AED", context: str = "",
                    language: str = "en") -> str:
    """Generate the customer reply via OpenAI. No offline fallback."""
    client, model, err = _client_and_model()
    if err:
        return f"[Reply unavailable: {err}. Add a valid OpenAI key (sk-...) to .env.]"

    brief = _decision_brief(action, amount=amount, currency=currency)
    output_language = (
        "Write the customer message in Modern Standard Arabic only. Keep product IDs, "
        "case IDs, currency codes, and amounts as written when needed."
        if language == "ar"
        else "Write the customer message in English only."
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.4,
            max_tokens=160,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a payment-support assistant writing the final "
                        "message a customer reads after their dispute was handled. "
                        "Write warm, clear, reassuring copy under 70 words. STRICT "
                        "RULES: follow the Decision exactly; never change the "
                        "decision, the amount, or any policy; never accuse the "
                        "customer of fraud; never promise a refund the Decision "
                        "does not state. Write in plain sentences and do not use "
                        "any dashes (no '-', '--' or '—'); use commas, periods, or "
                        "colons instead. " + output_language
                    ),
                },
                {
                    "role": "user",
                    "content": f"{brief}\n\nInternal context: {context}\n\n"
                               "Write the customer message now.",
                },
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or f"[Reply unavailable: empty response from {model}.]"
    except Exception as e:  # surface the real reason, do not fake a reply
        return (f"[Reply unavailable: OpenAI call failed ({type(e).__name__}: "
                f"{str(e)[:160]}). Check OPENAI_API_KEY in .env.]")
