"""Query analysis: follow-up condensation and tool routing.

Routing is rule-based first (deterministic, testable, free). Only when no rule fires AND an LLM is configured is
the LLM asked to choose among the fixed tool names; its answer is validated against that whitelist.
"""
from __future__ import annotations

import re

from app.rag.text_utils import tokenize
from app.services.llm import LLMUnavailable, extract_json

TOOLS = ("sql", "analytics", "rag", "external")
EXEC_ORDER = ("sql", "analytics", "rag", "external")

_DATA = re.compile(
    r"\b(revenue|sales|sold|orders?|aov|churn\w*|quarters?|q[1-4]|months?|monthly|quarterly|top \d+|top (three|five|ten)|"
    r"highest|lowest|best[- ]selling|worst|how many|total|count|kpis?|units|profit|margin|segments?|"
    r"average order|payments?|cancell?ed|pending orders|refunded orders|customers? (by|per|in)|"
    r"products?|regions?|categor(y|ies)|growth|declin\w*|decreas\w*|dropp?e?d?|increas\w*)\b", re.I)
_DOC = re.compile(
    r"\b(policy|policies|guidelines?|procedures?|handbook|strategy|strategies|documents?|internal reports?|"
    r"reports? (say|says|mention|state|explain|describe)|what do our (reports|documents)|according to|"
    r"mention\w*|our reports?|playbook|sop|process for|terms)\b", re.I)
_EXT = re.compile(r"\b(industry|market|competitors?|benchmarks?|trends?|external|on the web|online|web search|"
                  r"news|sector)\b", re.I)
_WHY = re.compile(r"\b(why|reasons?|causes?|explain|drivers?|due to|because)\b", re.I)
_FOLLOW_UP = re.compile(r"^(and|what about|how about|also|then|why|so|but)\b|\b(that|those|them|it|this|these|"
                        r"the same|previous one|above)\b", re.I)


def route_question(question: str) -> dict:
    """Return {"tools": [...], "reason": str, "ambiguous": bool}."""
    q = question.strip()
    has_data = bool(_DATA.search(q))
    has_doc = bool(_DOC.search(q))
    has_ext = bool(_EXT.search(q))
    why = bool(_WHY.search(q))
    tools: list[str] = []
    reasons: list[str] = []

    # A policy/guideline question that mentions a data-ish word ("refund policy") is a document question,
    # unless it also has an unambiguous numeric intent.
    strong_data = bool(re.search(r"\b(revenue|sales|orders|aov|churn\w*|quarter|q[1-4]|monthly|top \d+|highest|"
                                 r"lowest|best[- ]selling|how many|total|units|kpis?|segments?)\b", q, re.I))
    if has_doc and not strong_data:
        has_data = False

    if has_data:
        tools += ["sql", "analytics"]
        reasons.append("the question asks for business figures (SQL + analytics)")
        if has_doc or why:
            tools.append("rag")
            reasons.append("it also asks for reasons or what internal documents say (RAG)")
    elif has_doc:
        tools.append("rag")
        reasons.append("the question is about internal documents or policies (RAG)")
    if has_ext:
        tools.append("external")
        reasons.append("it refers to external market/industry information (external research)")
    ambiguous = not tools
    if ambiguous:
        tools = ["rag"]
        reasons.append("no specific data or document cue found; searching documents")
    ordered = [t for t in EXEC_ORDER if t in tools]
    return {"tools": ordered, "reason": "; ".join(reasons).capitalize() + ".", "ambiguous": ambiguous}


def llm_route(question: str, llm) -> list[str] | None:
    try:
        raw = llm.generate(
            "Choose which tools are needed to answer a business question. Tools: sql (query sales/orders/customers "
            "database), analytics (calculated KPIs/charts), rag (search internal documents), external (web research). "
            'Reply JSON only: {"tools": ["sql", ...]}. Use only the listed tool names.',
            f"Question: {question[:500]}", json_mode=True, max_tokens=80)
    except LLMUnavailable:
        return None
    obj = extract_json(raw) or {}
    tools = [t for t in obj.get("tools", []) if t in TOOLS] if isinstance(obj.get("tools"), list) else []
    if "sql" in tools and "analytics" not in tools:
        tools.append("analytics")
    return [t for t in EXEC_ORDER if t in tools] or None


def condense_question(question: str, history: list[dict], llm=None) -> str:
    """Turn a follow-up into a standalone question using only THIS conversation's history."""
    prior_users = [m["content"] for m in history if m.get("role") == "user"]
    if not prior_users:
        return question
    short = len(tokenize(question)) <= 8
    if not (short or _FOLLOW_UP.search(question)):
        return question
    if llm is not None and llm.configured():
        convo = "\n".join(f"{m['role']}: {str(m['content'])[:400]}" for m in history[-6:])
        try:
            out = llm.generate("Rewrite the user's last message as one standalone question that includes any "
                               "context needed from the conversation. Output only the question.",
                               f"{convo}\nuser: {question}", max_tokens=120).strip().strip('"')
            if 5 <= len(out) <= 400:
                return out
        except LLMUnavailable:
            pass
    return f"{prior_users[-1].strip()} (follow-up: {question.strip()})"
