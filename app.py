"""Streamlit UI for the Agentic Dispute Resolution Platform.

One unified help box: the customer verifies their identity (Emirates ID + OTP),
then describes any issue in a single message. The agent triages it, pulls that
customer's order, and resolves it, pausing for a human before any money moves.

Two audiences from one run:
  * Customers: a clean, plain-language help experience.
  * Reviewers / judges: a "Behind the scenes" panel + Audit and How-it-works tabs.
"""
from __future__ import annotations

import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import streamlit as st

from src.graph import run_case
from src.tools import (TOOL_CALL_LOG, TOOL_PERMISSIONS, get_customer,
                       get_orders_for_customer, reset_ledgers)
from src.fraud_engine import RISK_THRESHOLD
from src.identity import valid_eid_format
from src import case_store
from src.i18n import detect_language, dir_for, language_name, t

ADMIN_CODE = "tamkeen-staff"   # demo staff access code (see DEMO_LOGINS.txt)

DATA_CUSTOMERS = json.loads(
    (__import__("pathlib").Path(__file__).parent / "data" / "customers.json").read_text())

st.set_page_config(page_title="Help Center | Payments & Refunds", layout="centered")

# --------------------------------------------------------------------- styles
st.markdown("""
<style>
.block-container{max-width:820px}
.title{font-size:28px;font-weight:800;margin-bottom:2px}
.sub{color:#5b6472;margin-top:0;font-size:15px}
.card{border:1px solid #e7e9ee;border-radius:14px;padding:16px 20px;margin:12px 0;background:#fff}
.card-amber{border-left:5px solid #f59e0b;background:#fffaf2}
.card-green{border-left:5px solid #16a34a;background:#f3fbf6}
.card-blue {border-left:5px solid #2563eb;background:#f3f7ff}
.card-red  {border-left:5px solid #dc2626;background:#fef5f5}
.card-grey {border-left:5px solid #98a2b3;background:#f8fafc}
.headline{font-size:19px;font-weight:700;margin:0 0 6px 0}
.muted{color:#667085;font-size:13px;margin:4px 0}
.you{background:#eef2ff;border-radius:12px;padding:10px 14px;display:inline-block;max-width:92%}
.bot{background:#eafaf0;border-radius:12px;padding:10px 14px;display:inline-block;max-width:92%}
.pstep{margin:3px 0;font-size:14px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:9px;vertical-align:middle}
.dot-done{background:#16a34a}
.dot-now{background:#f59e0b}
.green{color:#137333}.amber{color:#b25e00}.grey{color:#667085}
.pill{display:inline-block;padding:3px 10px;border-radius:11px;font-size:12px;font-weight:700;margin:2px 6px 2px 0}
.pill-red{background:#fde8e8;color:#b91c1c}.pill-green{background:#e7f6ec;color:#137333}
.pill-amber{background:#fff4e5;color:#b25e00}.pill-grey{background:#eef0f3;color:#444}
.refnum{font-family:monospace;background:#f1f3f5;padding:2px 6px;border-radius:6px}
.rtl-scope{direction:rtl;text-align:right;font-family:"Segoe UI",Tahoma,Arial,sans-serif}
.rtl-scope .dot{margin-right:0;margin-left:9px}
.rtl-scope .card{border-left:1px solid #e7e9ee;border-right:5px solid #98a2b3}
.rtl-scope .card-amber{border-right-color:#f59e0b}.rtl-scope .card-green{border-right-color:#16a34a}
.rtl-scope .card-blue{border-right-color:#2563eb}.rtl-scope .card-red{border-right-color:#dc2626}
.rtl-scope .card-grey{border-right-color:#98a2b3}
.ltr-token{direction:ltr;unicode-bidi:isolate;display:inline-block}
</style>
""", unsafe_allow_html=True)

FRIENDLY_STEPS = [
    ("triage", "step_triage"),
    ("identity_verification", "step_identity"),
    ("evidence_retrieval", "step_evidence"),
    ("senior_support", "step_senior"),
    ("fraud_risk", "step_fraud"),
    ("policy", "step_policy"),
    ("legal_grounding", "step_legal"),
    ("decision", "step_decision"),
    ("human_approval", "step_human"),
    ("prepare_remedy", "step_prepare"),
    ("execute_refund", "step_execute"),
    ("audit_logger", "step_audit"),
]


def pill(text, kind="grey"):
    return f'<span class="pill pill-{kind}">{text}</span>'


def card(kind, headline, body):
    st.markdown(f'<div class="card card-{kind}"><div class="headline">{headline}</div>'
                f'<div>{body}</div></div>', unsafe_allow_html=True)


def ltr(value):
    return f'<span class="ltr-token">{value}</span>'


def apply_customer_direction(lang):
    direction = dir_for(lang)
    align = "right" if direction == "rtl" else "left"
    st.markdown(
        f"""
        <style>
        .block-container{{direction:{direction};text-align:{align}}}
        .block-container [data-testid="stMetricValue"],
        .block-container [data-testid="stDataFrame"],
        .block-container .refnum{{direction:ltr;text-align:left}}
        {'.block-container .dot{margin-right:0;margin-left:9px}' if direction == 'rtl' else ''}
        </style>
        """,
        unsafe_allow_html=True,
    )


def fmt_when(value):
    if not value:
        return t("not_scheduled")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        gst = dt.astimezone(timezone(timedelta(hours=4)))
        return gst.strftime("%d %b %Y, %H:%M GST")
    except ValueError:
        return value


def render_status_assurance(state, *, staff=False):
    if not state.customer_waiting_message:
        return
    lang = getattr(state, "language", "en") if not staff else "en"
    rows = [
        (t("owner", lang), state.assigned_owner or "Customer care"),
        (t("next_update_by", lang), ltr(fmt_when(state.next_update_at))),
        (t("sla_due", lang), ltr(fmt_when(state.sla_due_at))),
        (t("status", lang), t("status_" + (state.sla_status or "on_track"), lang)),
        (t("appeal_path", lang), t("available" if state.appeal_available else "not_needed", lang)),
    ]
    body = state.customer_waiting_message + "<br><br>" + "<br>".join(
        f"<b>{label}:</b> {value}" for label, value in rows
    )
    card("blue" if not staff else "grey", t("status_assurance", lang), body)
    if staff and state.follow_up_events:
        st.markdown("**Follow-up action log:**")
        st.dataframe(
            [{"type": e.get("type"), "scheduled": fmt_when(e.get("scheduled_at")),
              "message": e.get("message")} for e in state.follow_up_events],
            use_container_width=True, hide_index=True,
        )


def render_senior_support(state, *, staff=False):
    if not (state.senior_mode_enabled or state.is_senior):
        return
    lang = "en" if staff else getattr(state, "language", "en")
    rows = [
        (t("senior_safe_mode", lang), t("enabled" if state.senior_mode_enabled else "not_requested", lang)),
        (t("senior_customer", lang), t("yes" if state.is_senior else "not_declared", lang)),
        (t("detected_language", lang), language_name(getattr(state, "language", "en"))),
        (t("caregiver_updates", lang), t("authorized" if state.caregiver_authorized else "not_authorized", lang)),
    ]
    if state.caregiver_authorized:
        rows.extend([
            (t("caregiver", lang), state.caregiver_name or t("not_provided", lang)),
            (t("relationship", lang), state.caregiver_relationship or t("not_provided", lang)),
            (t("caregiver_phone", lang), ltr(state.caregiver_phone or t("not_provided", lang))),
        ])
    if state.senior_protection_flags:
        rows.append((t("protection_flags", lang), ", ".join(
            flag.replace("_", " ").title() for flag in state.senior_protection_flags)))
    body = "<br>".join(f"<b>{label}:</b> {value}" for label, value in rows)
    if state.senior_protection_summary:
        body += f"<br><br>{state.senior_protection_summary}"
    card("amber" if state.senior_protection_flags else "blue", t("senior_safe_support", lang), body)


# ----------------------------------------------------------- customer-facing UI
def render_chat(message, notice, lang="en"):
    st.markdown(f'<div class="muted">{t("you", lang)}</div><span class="you">{message}</span>',
                unsafe_allow_html=True)
    if notice:
        clean = notice.startswith("[Reply unavailable")
        if clean:
            st.markdown(f'<div class="muted" style="margin-top:10px">{t("support_assistant", lang)}</div>',
                        unsafe_allow_html=True)
            card("grey", t("reply_unavailable_title", lang), t("reply_unavailable_body", lang))
        else:
            st.markdown(f'<div class="muted" style="margin-top:10px">{t("support_assistant", lang)}</div>'
                        f'<span class="bot">{notice}</span>', unsafe_allow_html=True)


def render_progress(state):
    visited = {e.node_name for e in state.audit_events}
    current = state.current_step
    out = []
    lang = getattr(state, "language", "en")
    for node, label_key in FRIENDLY_STEPS:
        label = t(label_key, lang)
        if node in ("human_approval", "prepare_remedy", "execute_refund") and node not in visited:
            continue
        if node == current and state.human_approval_status == "PENDING" and node == "human_approval":
            out.append(f'<div class="pstep amber"><span class="dot dot-now"></span>{label}</div>')
        elif node in visited:
            out.append(f'<div class="pstep green"><span class="dot dot-done"></span>{label}</div>')
    st.markdown("".join(out), unsafe_allow_html=True)


def customer_card(state):
    lang = getattr(state, "language", "en")
    hs = state.human_approval_status
    pkg = state.refund_package
    if hs == "PENDING":
        card("amber", t("pending_title", lang), t("pending_body", lang))
    elif hs == "REJECTED":
        card("red", t("rejected_title", lang), t("rejected_body", lang))
    elif pkg is not None and pkg.status == "EXECUTED":
        card("green", t("refund_executed_title", lang),
             t("refund_executed_body", lang, amount=ltr(f"{pkg.currency} {pkg.amount:,.2f}")))
    elif pkg is not None:
        card("green", t("refund_prepared_title", lang),
             t("refund_prepared_body", lang, amount=ltr(f"{pkg.currency} {pkg.amount:,.2f}")))
    else:
        card("blue", t("no_refund_title", lang), t("no_refund_body", lang))
    render_status_assurance(state)


# --------------------------------------------------------- reviewer / internals
def render_signals(state):
    st.markdown("**Fraud signals (deterministic):**")
    st.dataframe([{"signal": s.code, "fired": "yes" if s.present else "no",
                   "weight": s.weight, "why": s.description} for s in state.risk_signals],
                 use_container_width=True, hide_index=True)


def render_policy(state):
    d = state.policy_decision
    if not d:
        return
    st.markdown("**Policy decision (grounded and cited):**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Policy version", d.policy_version)
    c2.metric("Rule fired", d.rule_id)
    c3.metric("Refund allowed", "Yes" if d.refund_allowed else "No")
    st.markdown(f'<div class="card card-grey"><b>{d.rule_id}</b>: {d.reason}</div>',
                unsafe_allow_html=True)


def render_legal(state, compact=False, show_text=False):
    if not state.legal_citations:
        return
    head = state.legal_source or "UAE Federal Law No. (15) of 2020 on Consumer Protection"
    rows = []
    for c in state.legal_citations:
        rows.append({"article": c.article_id.replace("Art.", "Article "),
                     "title": c.title.split(":", 1)[-1].strip() if ":" in c.title else c.title,
                     "via": "policy" if c.source == "policy_map" else "RAG retrieval",
                     "score": "" if c.score is None else f"{c.score:.3f}"})
    st.markdown(f"**Legal grounding (RAG over {head}):**")
    st.dataframe(rows, use_container_width=True, hide_index=True)
    # Note: no st.expander here. render_legal is sometimes called from inside an
    # expander, and Streamlit forbids nesting expanders. Show text inline instead.
    if show_text:
        st.caption("Cited article text:")
        for c in state.legal_citations:
            st.markdown(f"<b>{c.title}</b><br><span class='muted'>{c.text}</span>",
                        unsafe_allow_html=True)


def render_tool_calls(tool_log):
    st.markdown("**Tool calls (least privilege, read / prepare / execute separated):**")
    if not tool_log:
        st.caption("No tool calls recorded.")
        return
    st.dataframe([{"tool": t["tool"], "args": json.dumps(t["args"]),
                   "ok": "ok" if t["ok"] else "fail", "result": t["summary"]}
                  for t in tool_log], use_container_width=True, hide_index=True)


def render_execution_path(state):
    seq = []
    for e in state.audit_events:
        if e.decision == "PROMPT_INJECTION_ATTEMPT":
            continue
        if not seq or seq[-1] != e.node_name:
            seq.append(e.node_name)
    st.markdown("**Agent execution path:** `" + " -> ".join(seq) + "`")


def behind_the_scenes(state, tool_log, payments_view=False):
    with st.expander("Behind the scenes: agent internals (for reviewers and judges)"):
        rk = "red" if state.risk_score >= RISK_THRESHOLD else ("amber" if state.risk_score >= 40 else "green")
        st.markdown(pill(f"RISK {state.risk_score}/100", rk)
                    + pill(f"HUMAN: {state.human_approval_status}",
                           "amber" if state.human_approval_status == "PENDING" else "grey")
                    + (pill("SENIOR PROTECTION", "amber")
                       if state.senior_protection_flags else "")
                    + (pill("PROMPT-INJECTION BLOCKED", "red") if state.prompt_injection_detected else ""),
                    unsafe_allow_html=True)
        if state.prompt_injection_detected:
            st.caption(f"Override attempt ignored: “{state.prompt_injection_detail}”. "
                       "Logged as PROMPT_INJECTION_ATTEMPT, workflow unchanged.")
        if state.recovery_notes:
            st.caption("Recovery: " + " ".join(state.recovery_notes))
        render_execution_path(state)
        if payments_view and state.evidence.payments:
            st.markdown("**Payment forensics:**")
            st.dataframe([{"payment_id": p.get("payment_id"), "status": p.get("status"),
                           "amount": f"{p.get('currency')} {p.get('amount')}",
                           "type": p.get("type"), "note": p.get("note", "")}
                          for p in state.evidence.payments],
                         use_container_width=True, hide_index=True)
            st.caption(f"duplicate_charge_confirmed = {state.evidence.duplicate_charge_confirmed} . "
                       f"authorization_hold_present = {state.evidence.authorization_hold_present}")
        c1, c2 = st.columns(2)
        with c1:
            render_signals(state)
        with c2:
            render_policy(state)
        render_senior_support(state, staff=True)
        render_legal(state, show_text=True)
        render_tool_calls(tool_log)
        if state.refund_package:
            p = state.refund_package
            exe = f" . execution {p.execution_id}" if p.execution_id else ""
            rep = " . idempotent replay (no duplicate)" if p.idempotent_replay else ""
            st.markdown(f'<div class="card card-grey">Refund <span class="refnum">{p.refund_id}</span> '
                        f". status <b>{p.status}</b>{exe}{rep} . approved by "
                        f"{p.approved_by or 'pending'}</div>", unsafe_allow_html=True)


def render_audit_table(state):
    st.dataframe([{"time": e.timestamp.split("T")[-1][:12], "node": e.node_name,
                   "tool": e.tool_called or "", "risk": e.risk_score if e.risk_score is not None else "",
                   "policy": e.policy_version or "", "rule": e.rule_id or "",
                   "decision": e.decision or "", "human": e.human_approval_status or "",
                   "detail": e.detail or ""} for e in state.audit_events],
                 use_container_width=True, hide_index=True)


# ------------------------------------------------------------------- helpers
def customer_by_eid(eid):
    for cid, c in DATA_CUSTOMERS.items():
        if c.get("emirates_id") == (eid or "").strip():
            return cid, c
    return None, None


def order_for_customer(customer_id):
    orders = get_orders_for_customer(customer_id)
    return orders[0]["order_id"] if orders else None


def stash(state):
    st.session_state.last_state = state
    st.session_state.last_tools = list(TOOL_CALL_LOG)


def render_fraud(state):
    """The valuable fraud view: score, band, named typology, evidence, mitigation."""
    band = state.fraud_band or "LOW"
    color = {"HIGH": "red", "MEDIUM": "amber", "LOW": "green"}[band]
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("Fraud risk score", f"{state.risk_score}/100")
        st.progress(min(state.risk_score, 100) / 100)
        st.markdown(pill(f"BAND: {band}", color), unsafe_allow_html=True)
    with c2:
        card(color, f"Pattern detected: {state.fraud_typology}",
             f"<b>Recommended action:</b> {state.fraud_recommendation}")
    render_senior_support(state, staff=True)
    st.markdown("**Fraud signals and the evidence behind each one:**")
    st.dataframe([{"signal": s.code, "fired": "FIRED" if s.present else "no",
                   "weight": s.weight, "evidence": s.evidence or s.description}
                  for s in state.risk_signals], use_container_width=True, hide_index=True)


ARCH_DOT = r"""
digraph G {
  rankdir=TB; node [shape=box, style="rounded,filled", fontname="Helvetica", fillcolor="#eef2ff"];
  eid    [label="Emirates ID + OTP\n(verify BEFORE the dispute)", fillcolor="#f3f7ff"];
  req    [label="Customer Request (one box)", fillcolor="#e7f6ec"];
  triage [label="1. Triage\n(classify + injection guard)"];
  ident  [label="2. Identity Agent\nre-checks Emirates ID factors"];
  evid   [label="3. Evidence Retrieval\nget_order / get_payment / get_shipment\n+ retry and recovery"];
  fraud  [label="4. Fraud Risk Agent\nsignals to score + named typology", fillcolor="#fef4f4"];
  policy [label="5. Policy\npolicy_v1.json (versioned)"];
  law    [label="6. RAG Legal Agent\nUAE Law No.15/2020 (TF-IDF retrieval)", fillcolor="#f3f7ff"];
  dec    [label="7. Decision", fillcolor="#fff4e5"];
  human  [label="8. Staff Console\nagent SUPPORTS a human . PAUSE", fillcolor="#fde8e8"];
  remedy [label="Prepare Refund\n(checks + idempotency)"];
  exec   [label="Execute Refund\n(gated by approval token)", fillcolor="#fef4f4"];
  audit  [label="9. Audit Logger", fillcolor="#eef0f3"];
  done   [label="END / Customer Notice", shape=oval, fillcolor="#e7f6ec"];

  eid->req->triage->ident->evid->fraud->policy->law->dec;
  dec->human   [label="refund or high risk:\nhuman signs off", color="#b91c1c"];
  dec->remedy  [label="no money\n(explain only)", color="#137333"];
  human->remedy [label="APPROVED", color="#137333"];
  human->audit  [label="PENDING / REJECTED", color="#b91c1c"];
  remedy->exec->audit->done;
}
"""


# ----------------------------------------------------------------- CUSTOMER PAGE
def customer_page(outage):
    existing_rec = case_store.get(st.session_state.get("case", ""))
    existing_state = existing_rec["state"] if existing_rec else st.session_state.get("help_state")
    lang = getattr(existing_state, "language", detect_language(st.session_state.get("msg_main", "")))
    apply_customer_direction(lang)
    st.markdown(f'<p class="title">{t("page_title", lang)}</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="sub">{t("page_sub", lang)}</p>', unsafe_allow_html=True)
    st.caption(t("page_caption", lang))

    # ---- Step 1: identity verification (resolves which customer this is) ----
    if not st.session_state.get("verified"):
        card("blue", t("verify_step_title", lang), t("verify_step_body", lang))
        eid = st.text_input(t("eid_label", lang), key="eid_in",
                            placeholder="784-YYYY-NNNNNNN-N")
        col1, col2 = st.columns([1, 1])
        if col1.button(t("send_otp", lang), key="send_otp"):
            cid_lookup, c_lookup = customer_by_eid(eid)
            if cid_lookup:
                st.session_state.otp = f"{random.randint(0, 999999):06d}"
                st.session_state.otp_phone = c_lookup.get("registered_phone", "")
                st.session_state.pop("otp_error", None)
            else:
                st.session_state.pop("otp", None)
                st.session_state.otp_error = True
        if st.session_state.get("otp_error") and not st.session_state.get("otp"):
            card("red", t("eid_not_recognized_title", lang), t("eid_not_recognized_body", lang))
        otp = st.session_state.get("otp")
        if otp:
            col2.markdown(f'<div class="card card-grey">{t("mock_sms", lang, phone=ltr(st.session_state.get("otp_phone","")), otp=ltr(otp))}</div>',
                          unsafe_allow_html=True)
        otp_in = st.text_input(t("otp_label", lang), key="otp_in", max_chars=6, disabled=not otp)
        if st.button(t("verify_identity", lang), type="primary", use_container_width=True, disabled=not otp):
            cid, _ = customer_by_eid(eid)
            eid_ok = valid_eid_format(eid) and cid is not None
            otp_ok = bool(otp) and otp_in.strip() == otp
            if eid_ok and otp_ok:
                st.session_state.verified = True
                st.session_state.customer_id = cid
                st.session_state.factors = {"emirates_id": eid.strip(), "otp_verified": True}
                st.session_state.pop("otp_error", None)
                st.rerun()
            elif not eid_ok:
                card("red", t("could_not_verify_title", lang), t("could_not_verify_body", lang))
            else:
                card("red", t("incorrect_code_title", lang), t("incorrect_code_body", lang))
        return

    # ---- Step 2: one box for any issue ----
    cid = st.session_state.customer_id
    cust = get_customer(cid) or {}
    card("green", t("identity_verified_title", lang),
         t("identity_verified_body", lang, name=cust.get("name", cid)))
    if st.button(t("switch_identity", lang)):
        for k in ("verified", "customer_id", "factors", "otp", "case", "help_state",
                  "is_senior", "senior_mode_enabled", "preferred_language",
                  "caregiver_authorized", "caregiver_name", "caregiver_relationship",
                  "caregiver_phone"):
            st.session_state.pop(k, None)
        st.rerun()

    default_senior = bool(cust.get("senior_eligible"))
    card("blue", t("senior_optional_title", lang), t("senior_optional_body", lang))
    is_senior = st.checkbox(
        t("senior_checkbox", lang),
        value=st.session_state.get("is_senior", default_senior),
        key="is_senior",
    )
    senior_mode_enabled = st.checkbox(
        t("senior_mode_checkbox", lang),
        value=st.session_state.get("senior_mode_enabled", default_senior),
        key="senior_mode_enabled",
    )
    caregiver_authorized = st.checkbox(
        t("caregiver_checkbox", lang),
        value=st.session_state.get("caregiver_authorized", bool(cust.get("caregiver_authorized"))),
        key="caregiver_authorized",
    )
    caregiver_name = caregiver_relationship = caregiver_phone = None
    if caregiver_authorized:
        c1, c2 = st.columns(2)
        caregiver_name = c1.text_input(
            t("caregiver_name", lang),
            value=st.session_state.get("caregiver_name", cust.get("caregiver_name", "")),
            key="caregiver_name",
        )
        caregiver_relationship = c2.text_input(
            t("relationship", lang),
            value=st.session_state.get("caregiver_relationship", cust.get("caregiver_relationship", "")),
            key="caregiver_relationship",
        )
        caregiver_phone = st.text_input(
            t("caregiver_phone", lang),
            value=st.session_state.get("caregiver_phone", cust.get("caregiver_phone", "")),
            key="caregiver_phone",
        )

    st.markdown(f"**{t('message_prompt', lang)}**")
    msg = st.text_area("Your message", key="msg_main", label_visibility="collapsed",
                       placeholder=(t("placeholder_senior", lang)
                                    if senior_mode_enabled else t("placeholder_default", lang)))
    lang = detect_language(msg)

    f = st.session_state.factors
    run_kwargs = dict(
        case_id=st.session_state.get("case") or ("CASE-" + uuid.uuid4().hex[:6].upper()),
        customer_id=cid, order_id=order_for_customer(cid), customer_message=msg,
        provided_emirates_id=f["emirates_id"], otp_verified=f["otp_verified"],
        is_senior=is_senior, senior_mode_enabled=senior_mode_enabled,
        caregiver_authorized=caregiver_authorized,
        caregiver_name=caregiver_name, caregiver_relationship=caregiver_relationship,
        caregiver_phone=caregiver_phone,
        simulate_failures={"get_order"} if outage else None)
    st.session_state.case = run_kwargs["case_id"]

    if st.button(t("submit_request", lang), type="primary", use_container_width=True, disabled=not msg.strip()):
        s = run_case(**run_kwargs)
        case_store.upsert(s.case_id, state=s, run_kwargs=run_kwargs,
                          customer_name=cust.get("name", cid), issue=s.issue_type)
        st.session_state.help_state = s
        stash(s)

    # Always show the latest state from the shared store (so staff actions reflect here).
    rec = case_store.get(st.session_state.get("case", ""))
    s = rec["state"] if rec else st.session_state.get("help_state")
    if s:
        lang = getattr(s, "language", lang)
        st.divider()
        show_reply = s.human_approval_status != "PENDING"
        render_chat(s.customer_message, s.customer_notice if show_reply else None, lang)
        st.write("")
        render_senior_support(s)
        customer_card(s)
        if s.human_approval_status == "PENDING":
            st.caption(t("pending_caption", lang))
            if st.button(t("refresh_status", lang)):
                st.rerun()
        if s.legal_basis:
            st.markdown(f'<div class="card card-grey"><b>{t("rights_prefix", lang)}</b> '
                        f'{t("rights_body", lang, source=s.legal_source, basis=s.legal_basis)}</div>',
                        unsafe_allow_html=True)
        st.markdown(f'<div class="muted">{t("progress", lang)}</div>', unsafe_allow_html=True)
        render_progress(s)
        st.caption(t("reference", lang, case_id=s.case_id))


# -------------------------------------------------------------------- STAFF PAGE
def staff_page():
    st.markdown('<p class="title">Staff Console: Risk &amp; Dispute Review</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub">The agent prepares the case and a recommendation. A human '
                'reviewer signs off before any money moves.</p>', unsafe_allow_html=True)

    if not st.session_state.get("admin_authed"):
        card("blue", "Staff sign-in", "Restricted to risk reviewers.")
        who = st.text_input("Reviewer ID", value="risk.analyst@tamkeen", key="admin_who")
        code = st.text_input("Access code", type="password", key="admin_code")
        if st.button("Sign in", type="primary"):
            if code == ADMIN_CODE:
                st.session_state.admin_authed = True
                st.session_state.reviewer = who
                st.rerun()
            else:
                card("red", "Access denied", "Incorrect access code.")
        return

    st.caption(f"Signed in as {st.session_state.get('reviewer','reviewer')}.")
    t_queue, t_audit, t_arch = st.tabs(["Case queue", "Audit trail", "How it works"])

    with t_queue:
        cases = case_store.all_cases()
        pend = case_store.pending()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Open cases", len(cases))
        m2.metric("Awaiting review", len(pend))
        m3.metric("High-risk", sum(1 for c in cases if (c["state"].fraud_band == "HIGH")))
        m4.metric("SLA risk", sum(1 for c in cases if c.get("sla_status") in {"due_soon", "overdue"}))
        if not cases:
            st.info("No cases yet. Submit one from the Customer page (use the role switch in the sidebar).")
            return

        st.markdown("**Queue** (newest first; PENDING_REVIEW needs your decision):")
        st.dataframe([{"case": c["case_id"], "customer": c["customer_name"], "issue": c["issue"],
                       "language": language_name(getattr(c["state"], "language", "en")),
                       "risk": c["state"].risk_score, "band": c["state"].fraud_band,
                       "senior support": "yes" if c["state"].senior_mode_enabled else "",
                       "caregiver": "authorized" if c["state"].caregiver_authorized else "",
                       "priority": "protective review" if c["state"].senior_protection_flags else "",
                       "status": c["status"], "SLA": (c.get("sla_status") or "").replace("_", " "),
                       "next update": fmt_when(c.get("next_update_at"))} for c in cases],
                     use_container_width=True, hide_index=True)

        ids = [c["case_id"] for c in cases]
        sel = st.selectbox("Open a case", ids, index=0)
        rec = case_store.get(sel)
        s = rec["state"]

        st.divider()
        st.markdown(f"### Case {s.case_id}: {rec['customer_name']}")
        st.caption(f"Customer language: {language_name(getattr(s, 'language', 'en'))}")
        render_fraud(s)

        with st.expander("Evidence pack (identity, payments, policy, law)", expanded=False):
            st.markdown("**Identity factors:**")
            st.dataframe([{"factor": x["factor"], "passed": "yes" if x["passed"] else "no"}
                          for x in s.identity_factors], hide_index=True, use_container_width=True)
            if s.evidence.payments:
                st.markdown("**Payments:**")
                st.dataframe([{"payment_id": p.get("payment_id"), "status": p.get("status"),
                               "amount": f"{p.get('currency')} {p.get('amount')}", "type": p.get("type")}
                              for p in s.evidence.payments], hide_index=True, use_container_width=True)
            render_policy(s)
            render_legal(s, show_text=True)
            render_status_assurance(s, staff=True)

        if s.human_approval_status == "PENDING":
            st.markdown("#### Your decision")
            will_issue_refund = bool(s.policy_decision and s.policy_decision.action != "EXPLAIN_NO_REFUND")
            if will_issue_refund:
                st.caption("Approving will run the gated, idempotent execute_refund. Rejecting closes "
                           "the case with no money movement. The agent recommendation is above.")
            else:
                st.caption("Mark verified closes the protective review with an explanation. Rejecting "
                           "keeps the case closed with no money movement. The agent recommendation is above.")
            a1, a2 = st.columns(2)
            approve_label = "Approve and issue refund" if will_issue_refund else "Mark verified / close safely"
            if a1.button(approve_label, type="primary", use_container_width=True):
                ns = run_case(**rec["run_kwargs"], human_decision="APPROVE",
                              human_reviewer=st.session_state.get("reviewer", "reviewer"))
                case_store.upsert(ns.case_id, state=ns, run_kwargs=rec["run_kwargs"],
                                  customer_name=rec["customer_name"], issue=ns.issue_type)
                stash(ns)
                st.rerun()
            if a2.button("Reject", use_container_width=True):
                ns = run_case(**rec["run_kwargs"], human_decision="REJECT",
                              human_reviewer=st.session_state.get("reviewer", "reviewer"))
                case_store.upsert(ns.case_id, state=ns, run_kwargs=rec["run_kwargs"],
                                  customer_name=rec["customer_name"], issue=ns.issue_type)
                stash(ns)
                st.rerun()
        else:
            card("grey", f"Status: {rec['status']}", s.final_outcome or "Case complete.")

        behind_the_scenes(s, st.session_state.get("last_tools", []),
                          payments_view=(s.issue_type == "duplicate_charge"))

    with t_audit:
        st.subheader("Audit trail: complete, reproducible timeline")
        s = st.session_state.get("last_state")
        if not s:
            st.info("Open a case in the queue first.")
        else:
            st.markdown(f"**Case:** `{s.case_id}` . customer `{s.customer_id}` . "
                        f"issue `{s.issue_type}` . language `{language_name(getattr(s, 'language', 'en'))}` . "
                        f"policy `{s.policy_version}`")
            render_audit_table(s)
            with st.expander("Raw JSON (final state and tool-call log)"):
                st.json({"final_state": json.loads(s.model_dump_json()),
                         "tool_call_log": st.session_state.get("last_tools", [])})

    with t_arch:
        st.subheader("How it works: the agent graph")
        st.graphviz_chart(ARCH_DOT)
        st.markdown("""
**Two surfaces, one agent.** Customers get a clean help box; staff get a risk console
where the agent presents a named fraud typology, the evidence, and a recommendation,
and a human signs off before money moves. The status-assurance layer gives the
customer an owner, next update time, SLA due time, and appeal path.

| Rubric item | Where it lives |
|---|---|
| Working Agent Loop (25) | `src/graph.py`: LangGraph routing, pause/resume, retry + recovery on tool failure |
| Fraud + Human-in-the-Loop (20) | `src/fraud_engine.py` (named typologies + evidence + mitigation) + Staff Console |
| Tool Correctness + Least Privilege (15) | `TOOL_PERMISSIONS`: read / prepare / execute separated; idempotency + amount + policy checks |
| Auditability (15) | `AuditEvent` written by every node; Audit trail + raw JSON |
| Policy Grounding + Remedy (10) | `policy/policy_v1.json` + **RAG over UAE Law No.15/2020** (`src/rag.py`); decisions cite version, rule, and law articles |
| Demo Clarity (10) | separate Customer and Staff pages, real-vs-mocked panel |
| Innovation (5) | RAG legal agent + fraud typologies + prompt-injection defense + Emirates ID / OTP + status assurance |
""")


# ----------------------------------------------------------------------- router
if "last_state" not in st.session_state:
    st.session_state.last_state = None
    st.session_state.last_tools = []

with st.sidebar:
    st.markdown("### View")
    role = st.radio("I am", ["Customer", "Staff (risk reviewer)"], label_visibility="collapsed")

    st.markdown("### OpenAI (customer replies)")
    _key = os.getenv("OPENAI_API_KEY")
    _model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if _key and _key.startswith("sk-"):
        st.markdown(f'<div class="card card-green">Connected. Model '
                    f'<span class="refnum">{_model}</span>.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="card card-red">No valid OpenAI key in .env. Replies show an '
                    'error until OPENAI_API_KEY=sk-... is set. The agent still works.</div>',
                    unsafe_allow_html=True)

    st.markdown("### Demo controls")
    outage = st.checkbox("Simulate evidence-service outage", value=False,
                         help="Forces get_order to fail so you can watch the agent recover.")
    if st.button("Reset demo state"):
        reset_ledgers()
        case_store.reset()
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        st.rerun()
    with st.expander("Least-privilege tool matrix"):
        st.dataframe([{"node": k, "allowed tools": ", ".join(sorted(v)) or ""}
                      for k, v in TOOL_PERMISSIONS.items()], hide_index=True, use_container_width=True)
    st.caption(f"Human-review threshold: risk >= {RISK_THRESHOLD}. A human signs off "
               "before any money moves.")

if role == "Customer":
    customer_page(outage)
else:
    staff_page()
