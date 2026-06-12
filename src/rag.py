"""RAG agent: retrieves the relevant articles of UAE Federal Law No. (15) of 2020
on Consumer Protection and grounds the remedy in them.

The retriever is a small, dependency-free TF-IDF cosine ranker over article-level
chunks (`law/consumer_law_chunks.json`). It is deterministic, so the same dispute
always cites the same articles, which keeps the audit trail reproducible. The
retrieved snippets can optionally be summarised by the LLM, but the citations
themselves come from retrieval, not the model, so they can never be hallucinated.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

LAW_PATH = Path(__file__).resolve().parent.parent / "law" / "consumer_law_chunks.json"

_TOKEN = re.compile(r"[a-z]+")
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "be", "by", "with", "as", "at", "it", "its", "this", "that", "shall", "any",
    "from", "their", "they", "them", "not", "no", "if", "may", "was", "were",
}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 2]


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    data = json.loads(LAW_PATH.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    docs = []
    df: Counter = Counter()
    for c in chunks:
        toks = _tokens(c["text"]) + _tokens(c["title"]) + [t for tag in c["tags"] for t in _tokens(tag)]
        tf = Counter(toks)
        docs.append({"chunk": c, "tf": tf, "len": max(1, len(toks))})
        for term in set(toks):
            df[term] += 1
    n = len(docs)
    idf = {term: math.log((n + 1) / (cnt + 1)) + 1.0 for term, cnt in df.items()}
    # Pre-compute document vector norms.
    for d in docs:
        d["norm"] = math.sqrt(sum((tf / d["len"] * idf.get(term, 0.0)) ** 2
                                  for term, tf in d["tf"].items())) or 1.0
    return {"docs": docs, "idf": idf, "source": data["source"], "issued": data["issued"]}


def _score(query_tokens: list[str], doc: dict[str, Any], idf: dict[str, float]) -> float:
    if not query_tokens:
        return 0.0
    q_tf = Counter(query_tokens)
    q_len = max(1, len(query_tokens))
    q_norm = math.sqrt(sum((tf / q_len * idf.get(t, 0.0)) ** 2 for t, tf in q_tf.items())) or 1.0
    dot = 0.0
    for term, qtf in q_tf.items():
        if term in doc["tf"]:
            qw = qtf / q_len * idf.get(term, 0.0)
            dw = doc["tf"][term] / doc["len"] * idf.get(term, 0.0)
            dot += qw * dw
    return dot / (q_norm * doc["norm"])


def retrieve(query: str, k: int = 3, *, pin: list[str] | None = None) -> list[dict[str, Any]]:
    """Return the top-k most relevant law chunks for `query`.

    `pin` is a list of article_ids the policy already mapped to this rule; they
    are always included (and marked source=policy_map) and the rest are filled by
    semantic retrieval (source=retrieval).
    """
    idx = _index()
    q_tokens = _tokens(query)
    ranked = sorted(
        ({"chunk": d["chunk"], "score": round(_score(q_tokens, d, idx["idf"]), 4)} for d in idx["docs"]),
        key=lambda r: r["score"], reverse=True,
    )

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    pin = pin or []
    by_id = {d["chunk"]["article_id"]: d["chunk"] for d in idx["docs"]}
    for aid in pin:
        if aid in by_id and aid not in seen:
            results.append({"article_id": aid, "title": by_id[aid]["title"],
                            "text": by_id[aid]["text"], "score": None, "source": "policy_map"})
            seen.add(aid)
    for r in ranked:
        aid = r["chunk"]["article_id"]
        if aid in seen or r["score"] <= 0:
            continue
        results.append({"article_id": aid, "title": r["chunk"]["title"],
                        "text": r["chunk"]["text"], "score": r["score"], "source": "retrieval"})
        seen.add(aid)
        if len([x for x in results if x["source"] == "retrieval"]) >= k:
            break
    return results


# Query templates per issue type, enriched with the facts of the case.
def build_query(issue_type: str, facts: dict[str, Any]) -> str:
    parts = [issue_type.replace("_", " ")]
    if facts.get("delivery_confirmed"):
        parts.append("delivery confirmed proof of delivery not received refund reimburse")
    if issue_type == "duplicate_charge":
        parts.append("invoice price charged twice overcharge higher than declared price refund")
    if facts.get("duplicate_charge_confirmed"):
        parts.append("duplicate settled charge reimburse return value")
    if facts.get("authorization_hold_present"):
        parts.append("authorization hold not a separate charge invoice")
    if facts.get("evidence_incomplete"):
        parts.append("conflict dispute inspection experts verification")
    parts.append("consumer rights fair settlement compensation warranty return")
    return " ".join(parts)


def ground(issue_type: str, facts: dict[str, Any], pin: list[str] | None = None,
           k: int = 3) -> dict[str, Any]:
    """Top-level RAG entry: retrieve citations and a short grounded basis line."""
    idx = _index()
    citations = retrieve(build_query(issue_type, facts), k=k, pin=pin)
    ids = ", ".join(c["article_id"].replace("Art.", "Article ") for c in citations)
    basis = (f"Grounded in {idx['source']}: {ids}." if citations
             else "No specific article retrieved.")
    return {"source": idx["source"], "citations": citations, "basis": basis}
