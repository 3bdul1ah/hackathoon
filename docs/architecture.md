# Architecture

## 1. Principle: an agent, not a chatbot

The system is a **LangGraph state machine** with eight specialised nodes. It
plans (deterministic routing), holds typed state across steps, calls tools under
least privilege, grounds every decision in versioned policy, scores risk, pauses
for a human, and seals an audit trail. No free-form chat loop decides outcomes.

## 2. The graph (`src/graph.py`)

```
            ┌──────────┐
Customer ─▶ │  triage  │  classify issue_type + prompt-injection guard
            └────┬─────┘
                 ▼
      ┌──────────────────────┐
      │ identity_verification│  mocked identity check (passed / passed_with_flag / fail)
      └──────────┬───────────┘
                 ▼
      ┌──────────────────────┐
      │  evidence_retrieval  │  get_order · get_payment · get_shipment (READ tools)
      └──────────┬───────────┘
                 ▼
      ┌──────────────────────┐
      │     fraud_risk       │  deterministic signals → score 0..100
      └──────────┬───────────┘
                 ▼
      ┌──────────────────────┐
      │       policy         │  evaluate policy_v1.json → rule_id + action
      └──────────┬───────────┘
                 ▼
      ┌──────────────────────┐
      │   legal_grounding    │  RAG: search_law → cite UAE Law No.15/2020 articles
      └──────────┬───────────┘
                 ▼
      ┌──────────────────────┐
      │      decision        │  refund or high risk? a human signs off
      └────┬─────────────┬───┘
   no money│             │refund or high risk
  (explain)▼             ▼
   ┌───────────────┐  ┌──────────────────┐
   │ prepare_remedy│  │  human_approval  │ create_risk_case · PAUSE (no refund)
   └──────┬────────┘  └───┬──────────┬───┘
          │      approved │          │ pending / rejected
          │◀──────────────┘          │
          ▼                          ▼
   ┌───────────────┐                 │
   │ execute_refund│ gated by token  │
   └──────┬────────┘                 │
          ▼                          ▼
   ┌──────────────────────────────────────┐
   │            audit_logger              │  seals case + final customer notice
   └──────────────────┬───────────────────┘
                      ▼
                     END
```

### Pause / resume (human-in-the-loop)

The graph is deterministic, so human-in-the-loop is implemented as **pause +
re-run**:

1. First invocation with `human_decision=None`. On a high-risk case the
   `human_approval` node opens a risk case via `create_risk_case`, sets
   `human_approval_status="PENDING"`, prepares **no** refund, and the graph ends.
2. The UI shows Approve / Reject buttons. On click, the graph is re-invoked with
   `human_decision="APPROVE"|"REJECT"`. Because every engine is deterministic the
   re-run reproduces the identical risk/policy trace, then routes:
   `APPROVE → prepare_remedy`, `REJECT/PENDING → audit_logger` (no refund).

## 3. Typed state (`src/state.py`)

`CaseState` (Pydantic v2) is the single source of truth threaded through every
node. Required fields: `case_id, customer_id, issue_type, identity_verified,
evidence, risk_score, risk_signals, policy_version, recommended_action,
human_approval_status, audit_events, customer_notice, current_step`, plus
supporting `policy_decision`, `refund_package`, prompt-injection flags, and
`final_outcome`. Each node returns a partial dict that LangGraph merges in.

## 4. Tools & least privilege (`src/tools.py`)

| Class | Tool | Purpose |
|---|---|---|
| READ | `get_order`, `get_payment`, `get_shipment`, `get_orders_for_customer` | retrieve mock records only (the last is the recovery lookup) |
| RISK | `create_risk_case` | open a manual-review case (no money movement) |
| PREPARE | `prepare_refund` | assemble a refund package after amount + policy + idempotency checks |
| EXECUTE | `execute_refund` | move money, gated by an approval token and idempotent |

`TOOL_PERMISSIONS` pins exactly which node may call which tool and raises on any
violation, so least privilege is *enforced and verifiable*, not just documented.
`prepare_remedy` may PREPARE but not EXECUTE; `execute_refund` may EXECUTE but not
PREPARE. Execution never happens without an approval token, so **no refund is ever
auto-executed**: a human signs off first.

## 5. Fraud engine (`src/fraud_engine.py`)

Five deterministic, additive signals (capped at 100):

| Signal | Weight |
|---|---|
| DELIVERY_CONFIRMED | 30 |
| RECENT_ACCOUNT_CHANGE | 25 |
| PREVIOUS_REFUND_ISSUED | 20 |
| MULTIPLE_REFUND_ATTEMPTS | 20 |
| IDENTITY_VERIFICATION_FAILURE | 25 |

`score ≥ 70 → human review`. Same evidence ⇒ same score, every time.

## 6. Policy engine (`policy/policy_v1.json` + `src/policy_engine.py`)

Policy is **data, not code**, with a `policy_version`. Rules are evaluated
top-to-bottom; the first whose conditions all match wins; `R-000` (empty
conditions) is the safe fallback that routes to a human. Every decision cites
`policy_version`, `rule_id`, and `decision_reason`.

## 6b. RAG legal agent (`src/rag.py` + `law/`)

After the internal policy decision, the `legal_grounding` node grounds the remedy
in the **actual UAE Federal Law No. (15) of 2020 on Consumer Protection**:

- `law/consumer_law_chunks.json` holds 15 article-level chunks (Art. 1 definitions,
  4, 8, 10, 12, 13, 15, 19, 21, 23, 24, 25, 35).
- `src/rag.py` is a small, dependency-free **TF-IDF cosine retriever** (no external
  vector DB, so it runs anywhere and is fully deterministic).
- The node **pins** the articles the matched policy rule maps to (`legal_refs`) and
  lets retrieval surface additional relevant ones. Each citation is tagged
  `policy_map` or `retrieval`.
- The read is exposed as the least-privilege tool `search_law`, granted only to the
  `legal_grounding` node.
- Because citations come from retrieval (not a language model), they **cannot be
  hallucinated**; the LLM only words the final customer message.

Examples: a duplicate-charge dispute cites **Art. 8** (detailed invoice) and
**Art. 19** (no charging above the declared price); a non-receipt refund cites
**Art. 10 / 12 / 15** (replace or return the value); any contested case cites
**Art. 23** (experts for disputes) and **Art. 24** (compensation, misuse excluded).

## 7. Audit trail (`AuditEvent`)

Every node appends one immutable event: `timestamp, node_name, tool_called,
evidence_used, risk_score, decision, policy_version, rule_id,
human_approval_status, customer_notice, detail`. The `audit_logger` node seals
the case. The full timeline is visible in UI Tab 3 and as raw JSON.

## 8. Prompt-injection defense (`src/injection_guard.py`)

The customer message is untrusted. `triage` scans it for override/escalation
phrases; on a hit it logs `PROMPT_INJECTION_ATTEMPT` and **continues the normal
workflow unchanged**, the attempt has zero effect on routing, risk, or policy.
