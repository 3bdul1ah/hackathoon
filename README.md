# 🛡️ Agentic Payments, Billing & Consumer Dispute Resolution Platform

Tamkeen 5.0, Advanced Track. A **LangGraph agent** (not a chatbot) that resolves
payment disputes with planning, stateful execution, least-privilege tools,
versioned policy grounding, deterministic fraud scoring, a real human-in-the-loop
gate, and a complete audit trail.

> **Safety invariant:** no refund is ever executed automatically. The only
> money-adjacent tool is `prepare_refund`, which assembles a package behind the
> human-approval gate. There is deliberately **no `execute_refund` tool anywhere**.

## Quickstart

```bash
pip install -r requirements.txt

# Generate sample outputs for both scenarios (writes to outputs/)
python run_scenarios.py

# Launch the demo UI (4 tabs: Scenario A, Scenario B, Audit Trail, Architecture)
streamlit run app.py
```

**Customer replies are generated live by the OpenAI API** using `OPENAI_API_KEY`
in `.env` (optionally `OPENAI_MODEL`, default `gpt-4o-mini`). There is no offline
fallback: if the key is missing or invalid, replies show a clear error. The
*decision* itself (refund / review / no refund) is computed by the deterministic
fraud and policy engines and passed to the model as grounding, so wording can
never change a decision, amount, or policy.

For real email OTPs, set `SUPABASE_URL` and `SUPABASE_KEY` in `.env` and install
the `supabase` Python package. Without those values, the login step falls back to
a local demo code so the UI still runs.

> Put a real OpenAI key (`OPENAI_API_KEY=sk-...`) in `.env`. A GitHub token
> (`ghp_...`) or any non-`sk-` value will fail with a 401.

## The two required scenarios

**A. Suspicious refund** (`CUST-1001` / `ORD-A-100`): "I never received my AED 3500
laptop." Delivery is confirmed, the account email changed 3 days ago, a goodwill
credit was already issued, and there were prior refund attempts → **risk 95** →
policy rule **R-001** → autonomous execution **PAUSES** → routed to a human. Approve
to prepare the refund package; reject to close with no refund. **No auto-refund.**

**B. "Charged twice"** (`CUST-2002` / `ORD-B-200`): the agent retrieves both
payments, sees **one authorization hold + one settled charge** for the *same* order,
distinguishes a temporary hold from a true duplicate (rule **R-004**), and explains
that no refund is owed. (If the data were two *settled* charges, rule **R-003**
would prepare a refund.)

## Folder structure

```
hackathon/
├── app.py                  # Streamlit UI (4 tabs)
├── run_scenarios.py        # CLI: runs both scenarios, writes outputs/
├── requirements.txt
├── policy/
│   └── policy_v1.json      # versioned policy engine (data, not code)
├── data/                   # mock datasets
│   ├── customers.json  orders.json  payments.json  shipments.json
├── src/
│   ├── state.py            # Pydantic typed state model + AuditEvent
│   ├── tools.py            # least-privilege tools + TOOL_PERMISSIONS matrix
│   ├── fraud_engine.py     # signals → score + named fraud typology + mitigation
│   ├── policy_engine.py    # versioned, file-driven rule evaluation
│   ├── injection_guard.py  # prompt-injection / policy-override defense
│   ├── identity.py         # Emirates ID + email OTP verification (mocked)
│   ├── case_store.py       # shared in-process queue (Customer page → Staff console)
│   ├── rag.py              # RAG agent: TF-IDF retrieval over the UAE law
│   ├── notice.py           # customer notices (generated live by OpenAI)
│   └── graph.py            # the LangGraph agent workflow
├── law/
│   ├── Federal Law No. (15) of 2020 on Consumer Protection.pdf
│   └── consumer_law_chunks.json   # article-level chunks for the RAG retriever
├── DEMO_LOGINS.txt         # demo identities / Emirates IDs for the live demo
├── outputs/                # generated sample runs (JSON)
└── docs/
    ├── architecture.md  demo_script.md  judge_mapping.md
```

## The agent graph

```
Verify Emirates ID + email OTP  (BEFORE the dispute)
   → Triage → Identity → Evidence (retry + recovery) → Fraud → Policy
   → RAG Legal Agent (UAE Law No.15/2020) → Decision
   No money (explain)      → Prepare Remedy → Execute (skipped) → Audit → END
   Refund or high risk     → Reviewer Console (human signs off)
                               approved → Prepare Refund → Execute → Audit → END
                               pending/rejected → Audit → END (no money moves)
```

Every remedy is grounded twice: in the **versioned internal policy** (`policy_v1.json`)
and in the **actual UAE Consumer Protection Law**, retrieved by a deterministic RAG
agent (`src/rag.py`) and cited by article in the UI and audit trail.

**The agent supports the human, it does not replace them.** Every refund needs a
human sign-off before `execute_refund` moves money; the agent's job is to prepare a
full evidence pack and a recommendation. `prepare_refund` and `execute_refund` enforce
amount, policy, approval-token and idempotency checks.

See `docs/judge_mapping.md` for a line-by-line mapping of every rubric item to code.
