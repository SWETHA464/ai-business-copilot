"""Central LangGraph orchestrator.

Graph:  analyze -> router -(conditional)-> sql_agent | analytics_agent | rag_agent | research_agent -> router ...
        router (nothing left) -> verify -(retry once if RAG evidence was thin)-> rag_agent | respond -> END

* Only the tools the question needs are run (see graph/routing.py).
* Limits: MAX_STEPS tool dispatches, one RAG retry, LangGraph recursion limit, per-node error isolation.
* Human approval: external web research only runs when the user explicitly allows it for that message.
* Numbers shown to the user come from analytics/SQL; an LLM answer is discarded if it contains numbers that are not
  in the computed facts.
"""
from __future__ import annotations

import json
import operator
import re
import time
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.agents.rag_agent import answer as rag_answer
from app.agents.research_agent import ResearchAgent
from app.agents.sql_agent import DESTRUCTIVE, SQLAgent, summarize_rows
from app.database.session import get_readonly_engine
from app.graph.routing import condense_question, llm_route, route_question
from app.rag.retrieval import RetrievalConfig, retrieve
from app.security.prompt_guard import UNTRUSTED_NOTICE, wrap_untrusted
from app.services import analytics_service as A
from app.services.llm import LLMUnavailable, get_llm
from app.services.narrative import describe_analytics
from app.utils.logging import get_logger

log = get_logger("graph")
MAX_STEPS = 8
NODE_BY_TOOL = {"sql": "sql_agent", "analytics": "analytics_agent", "rag": "rag_agent", "external": "research_agent"}
MAX_SQL_ROWS_RETURNED = 50


class GraphState(TypedDict, total=False):
    question: str
    history: list[dict]
    standalone: str
    allow_external: bool
    category: str | None
    department: str | None
    force_tools: list[str] | None
    plan: list[str]
    done: list[str]
    route_reason: str
    step_count: int
    retries: dict
    retry_target: str | None
    sql: dict | None
    analytics: dict | None
    rag: dict | None
    research: dict | None
    verification: dict
    needs_approval: list[dict]
    final: dict
    steps: Annotated[list, operator.add]
    warnings: Annotated[list, operator.add]


# ----------------------------------------------------------------------------- helpers
def _deps(config: RunnableConfig) -> dict:
    return config["configurable"]


def _timed(name: str):
    """Wrap a node: time it, isolate exceptions, record a step."""
    def deco(fn):
        def wrapper(state: GraphState, config: RunnableConfig) -> dict:
            t0 = time.perf_counter()
            try:
                out = fn(state, config)
                detail = out.pop("_detail", "")
                err = None
            except Exception as exc:  # a failing tool must not take the whole request down
                log.exception("node %s failed", name)
                out, detail, err = {}, "", type(exc).__name__
                out["warnings"] = [f"The {name.replace('_', ' ')} step failed and was skipped."]
                tool = next((t for t, n in NODE_BY_TOOL.items() if n == name), None)
                if tool:
                    out["done"] = state.get("done", []) + [tool]
            ms = round((time.perf_counter() - t0) * 1000, 1)
            out["steps"] = out.get("steps", []) + [{"node": name, "ms": ms, "detail": detail, "error": err}]
            log.info("node=%s ms=%.0f error=%s", name, ms, err)
            return out
        return wrapper
    return deco


def _done(state: GraphState, tool: str) -> list[str]:
    return state.get("done", []) + [tool]


# ----------------------------------------------------------------------------- nodes
@_timed("analyze")
def analyze(state: GraphState, config: RunnableConfig) -> dict:
    llm = _deps(config)["llm"]
    standalone = condense_question(state["question"], state.get("history", []), llm)
    forced = state.get("force_tools")
    if forced:
        route = {"tools": list(forced), "reason": "Report mode uses every relevant source.", "ambiguous": False}
    else:
        route = route_question(standalone)
        if route["ambiguous"] and llm.configured():
            picked = llm_route(standalone, llm)
            if picked:
                route = {"tools": picked, "reason": "The model selected tools for an ambiguous question.", "ambiguous": False}
    plan, approvals, warnings = list(route["tools"]), [], []
    q = state["question"]
    if DESTRUCTIVE.search(q) or re.match(r"^\s*(select|with)\b", q, re.I):
        plan = ["sql"]            # the SQL guard answers (blocks or runs) this alone; no unrelated analytics
        route = {**route, "reason": "The request is SQL or asks to modify data, so only the guarded SQL tool handles it."}
    if "external" in plan and not state.get("allow_external"):
        plan.remove("external")
        approvals.append({"tool": "external_research",
                          "message": "This question could use external web research. Enable 'Allow external "
                                     "web search' and ask again to include it; no query has been sent."})
    return {"standalone": standalone, "plan": plan, "done": [], "route_reason": route["reason"], "step_count": 0,
            "retries": {"rag": 0}, "retry_target": None, "needs_approval": approvals, "warnings": warnings,
            "_detail": f"plan={plan}"}


@_timed("router")
def router(state: GraphState, config: RunnableConfig) -> dict:
    return {"step_count": state.get("step_count", 0) + 1}


def pick_next(state: GraphState) -> str:
    if state.get("step_count", 0) > MAX_STEPS:
        return "verify"
    for tool in state.get("plan", []):
        if tool not in state.get("done", []):
            return NODE_BY_TOOL[tool]
    return "verify"


@_timed("sql_agent")
def sql_agent(state: GraphState, config: RunnableConfig) -> dict:
    res = SQLAgent(engine_getter=lambda: get_readonly_engine(), llm=_deps(config)["llm"]).run(state["standalone"])
    out: dict[str, Any] = {"sql": res, "done": _done(state, "sql"), "_detail": f"status={res['status']} source={res.get('source')}"}
    if res["status"] in ("blocked", "error", "unavailable"):
        out["warnings"] = [res["message"]]
    return out


@_timed("analytics_agent")
def analytics_agent(state: GraphState, config: RunnableConfig) -> dict:
    try:
        with get_readonly_engine().connect() as conn:
            sales, customers, payments = A.load_frames(conn)
    except Exception:
        return {"analytics": {"status": "error"}, "done": _done(state, "analytics"),
                "warnings": ["The business database is unavailable, so calculated analytics could not be produced."]}
    if sales.empty:
        return {"analytics": {"status": "no_data"}, "done": _done(state, "analytics"),
                "warnings": ["The business database has no orders yet. Run scripts/seed_database.py."]}
    res = A.analyze_question(state["standalone"], sales, customers, payments)
    res["status"] = "ok"
    res["bullets"] = describe_analytics(res)
    return {"analytics": res, "done": _done(state, "analytics"), "_detail": f"intent={res['intent']}"}


@_timed("rag_agent")
def rag_agent(state: GraphState, config: RunnableConfig) -> dict:
    d = _deps(config)
    retry = state.get("retries", {}).get("rag", 0)
    cfg = RetrievalConfig.from_settings()
    if state.get("retry_target") == "rag":            # broadened second attempt
        cfg.candidates *= 2
        cfg.top_k += 4
        cfg.n_query_variants += 1
        retry += 1
    res = retrieve(d["db"], state["standalone"], d["user"], config=cfg, category=state.get("category"),
                   department=state.get("department"), llm=d["llm"])
    ans = rag_answer(state["standalone"], res, d["llm"])
    rag = {**ans, "sufficient": res.sufficient, "coverage": res.coverage, "queries": res.queries,
           "timings_ms": res.timings_ms, "searched_documents": res.searched_documents, "reason": res.reason,
           "_passages": [{"n": i, "filename": h.filename, "page": h.page, "text": h.compressed or h.text}
                         for i, h in enumerate(res.hits[:5], start=1)]}
    return {"rag": rag, "done": state.get("done", []) if state.get("retry_target") == "rag" else _done(state, "rag"),
            "retries": {**state.get("retries", {}), "rag": retry}, "retry_target": None,
            "_detail": f"hits={len(res.hits)} sufficient={res.sufficient} retry={retry}"}


@_timed("research_agent")
def research_agent(state: GraphState, config: RunnableConfig) -> dict:
    res = ResearchAgent().search(state["standalone"])
    out: dict[str, Any] = {"research": res, "done": _done(state, "external"), "_detail": f"status={res['status']}"}
    if res["status"] != "ok":
        out["warnings"] = [res["message"]]
    return out


def _cross_check(sql: dict | None, analytics: dict | None) -> str | None:
    """Compare per-product revenue where SQL and pandas answer the same question."""
    if not sql or sql.get("status") != "ok" or not analytics or analytics.get("status") != "ok":
        return None
    cols = [c.lower() for c in sql.get("columns", [])]
    prods = analytics.get("metrics", {}).get("products")
    if "revenue" not in cols or "product" not in cols or not prods:
        return None
    ri, pi = cols.index("revenue"), cols.index("product")
    ref = {p["product"]: p["revenue"] for p in prods}
    pairs = [(r[pi], r[ri]) for r in sql["rows"] if r[pi] in ref]
    if not pairs:
        return None
    ok = all(abs(float(v) - ref[k]) <= 0.01 for k, v in pairs)
    return "match" if ok else "mismatch"


@_timed("verify")
def verify(state: GraphState, config: RunnableConfig) -> dict:
    sql, an, rag, rs = state.get("sql"), state.get("analytics"), state.get("rag"), state.get("research")
    checks: list[dict] = []
    if sql is not None:
        checks.append({"check": "SQL validated and executed read-only", "ok": sql["status"] == "ok",
                       "detail": sql["status"] if sql["status"] != "ok" else f"{sql['row_count']} row(s)"})
    if an is not None:
        checks.append({"check": "Analytics computed from database", "ok": an.get("status") == "ok",
                       "detail": an.get("intent", an.get("status", ""))})
    cc = _cross_check(sql, an)
    if cc:
        checks.append({"check": "SQL result agrees with pandas calculation", "ok": cc == "match",
                       "detail": cc if cc == "match" else "figures differ; they may cover different periods"})
    if rag is not None:
        checks.append({"check": "Document evidence found and cited", "ok": rag["status"] == "ok" and bool(rag["citations"]),
                       "detail": f"{len(rag['citations'])} source(s), coverage {rag['coverage']}"})
    if rs is not None:
        checks.append({"check": "External sources retrieved", "ok": rs["status"] == "ok", "detail": rs["status"]})
    out: dict[str, Any] = {"verification": {"checks": checks, "all_ok": all(c["ok"] for c in checks) if checks else False}}
    thin = rag is not None and rag["status"] != "ok"
    if thin and state.get("retries", {}).get("rag", 0) < 1 and state.get("step_count", 0) <= MAX_STEPS:
        out["retry_target"] = "rag"
        out["_detail"] = "RAG evidence thin: retrying once with a broader search"
    return out


def after_verify(state: GraphState) -> str:
    return "rag_agent" if state.get("retry_target") == "rag" else "respond"


# ----------------------------------------------------------------------------- answer composition
_NUM = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?")


def _num_tokens(text: str) -> set[float]:
    out = set()
    for m in _NUM.findall(text):
        try:
            out.add(round(float(m.replace("$", "").replace(",", "")), 2))
        except ValueError:
            pass
    return out


def numbers_verified(answer: str, facts: str) -> tuple[bool, list[float]]:
    allowed = {abs(a) for a in _num_tokens(facts)}
    bad = []
    for v in _num_tokens(re.sub(r"\[\d+\]", "", answer)):
        v = abs(v)
        if v.is_integer() and (v <= 12 or 2000 <= v <= 2100):   # list counters, small counts, years
            continue
        if not any(abs(v - a) <= 0.011 or (a and abs(v - a) / a <= 0.0005) for a in allowed):
            bad.append(v)
    return (not bad), bad


def sql_for_api(sql: dict | None) -> dict | None:
    if not sql:
        return None
    return {"status": sql["status"], "source": sql.get("source"), "query": sql.get("sql", ""),
            "params": sql.get("params", {}), "columns": sql.get("columns", []),
            "rows": sql.get("rows", [])[:MAX_SQL_ROWS_RETURNED], "row_count": sql.get("row_count", 0),
            "truncated": bool(sql.get("truncated")) or sql.get("row_count", 0) > MAX_SQL_ROWS_RETURNED,
            "elapsed_ms": sql.get("elapsed_ms", 0), "message": sql.get("message", ""),
            "description": sql.get("description", "")}


def _sql_chart(sql: dict | None) -> dict | None:
    """Simple bar chart for a (label, number) SQL result when analytics produced none."""
    if not sql or sql.get("status") != "ok" or not 2 <= len(sql["rows"]) <= 30 or len(sql["columns"]) < 2:
        return None
    cols, rows = sql["columns"], sql["rows"]
    num_idx = [i for i in range(len(cols)) if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)]
    lab_idx = [i for i in range(len(cols)) if i not in num_idx and not str(cols[i]).lower().endswith("id")]
    if not num_idx or not lab_idx:
        return None
    li, ni = lab_idx[0], num_idx[-1]
    return A.chart("bar", f"{cols[ni].replace('_', ' ').title()} by {cols[li].replace('_', ' ')}", cols[li],
                   [(cols[ni], cols[ni].replace("_", " ").title())],
                   [{cols[li]: str(r[li]), cols[ni]: r[ni]} for r in rows], "currency" if "revenue" in cols[ni].lower() else "number")


def deterministic_answer(state: GraphState) -> str:
    parts: list[str] = []
    an, sql, rag, rs = state.get("analytics"), state.get("sql"), state.get("rag"), state.get("research")
    if an and an.get("status") == "ok" and an.get("bullets"):
        parts.append("**Verified figures (calculated from the database)**\n" + "\n".join(f"- {b}" for b in an["bullets"]))
    elif sql and sql["status"] == "ok":
        parts.append("**Database query result**\n" + summarize_rows(sql["columns"], sql["rows"]))
    if sql and sql["status"] == "blocked":
        parts.insert(0, sql["message"])
    elif sql and sql["status"] in ("unavailable", "error") and not (an and an.get("status") == "ok"):
        parts.append(sql["message"])
    if rag is not None:
        parts.append("**From internal documents**\n" + rag["answer"])
    if rs is not None and rs["status"] == "ok":
        parts.append("**External research (web sources, not verified against internal data)**\n" +
                     "\n".join(f"- {r['title']}: {r['snippet'][:220].strip()} ({r['url']})" for r in rs["results"][:4]))
    elif rs is not None:
        parts.append("**External research**\n" + rs["message"])
    for a in state.get("needs_approval", []):
        parts.append(a["message"])
    return "\n\n".join(parts) if parts else "I could not find anything to answer this question."


def _facts(state: GraphState) -> str:
    chunks: list[str] = []
    an, sql, rag, rs = state.get("analytics"), state.get("sql"), state.get("rag"), state.get("research")
    if an and an.get("status") == "ok":
        chunks.append("CALCULATED FIGURES (authoritative):\n" + "\n".join(an.get("bullets", [])))
        chunks.append("DEFINITIONS:\n" + "\n".join(an.get("definitions", [])))
    if sql and sql["status"] == "ok":
        chunks.append("SQL RESULT: " + summarize_rows(sql["columns"], sql["rows"], limit=10))
    if rag and rag["status"] == "ok":
        chunks.append("DOCUMENT EVIDENCE:\n" + "\n".join(wrap_untrusted(f"Source [{p['n']}] {p['filename']}", p["text"])
                                                           for p in rag.get("_passages", [])))
    if rs and rs["status"] == "ok":
        chunks.append("EXTERNAL WEB RESULTS:\n" + "\n".join(
            wrap_untrusted(f"Web: {r['title']} {r['url']}", r["snippet"]) for r in rs["results"][:4]))
    return "\n\n".join(chunks)


LLM_SYSTEM = (
    "You are a business analyst assistant. Write a concise answer (under 200 words) using ONLY the facts provided. "
    "Rules: copy every number exactly as written in the facts and never compute or estimate new numbers; do not "
    "state causes that the document evidence does not state - if documents do not explain something, say so; "
    "keep sections separate and labelled: figures (from the database), internal documents (cite as [n]), external "
    "research (say it is from the web). If a section has no facts, omit it. " + UNTRUSTED_NOTICE)


@_timed("respond")
def respond(state: GraphState, config: RunnableConfig) -> dict:
    llm = _deps(config)["llm"]
    an, sql, rag, rs = state.get("analytics"), state.get("sql"), state.get("rag"), state.get("research")
    warnings = list(dict.fromkeys(state.get("warnings", [])))
    answer, llm_used = deterministic_answer(state), False
    facts = _facts(state)
    has_data = bool(an and an.get("status") == "ok") or bool(sql and sql["status"] == "ok")
    has_docs = bool(rag and rag["status"] == "ok")
    if llm.configured() and (has_data or has_docs or (rs and rs["status"] == "ok")):
        try:
            draft = llm.generate(LLM_SYSTEM, f"Question: {state['question']}\n\nFACTS:\n{facts}", max_tokens=600).strip()
            ok, bad = numbers_verified(draft, facts + " " + answer)
            if draft and ok:
                answer, llm_used = draft, True
            else:
                warnings.append("The model's wording contained figures that were not in the calculated results, so the "
                                "verified summary is shown instead.")
        except LLMUnavailable:
            warnings.append("The language model is unavailable; showing the verified summary without AI wording.")
    elif not llm.configured():
        warnings.append("No language model is configured; answers are assembled directly from calculated results "
                        "and document excerpts.")

    charts = list(an.get("charts", [])) if an and an.get("status") == "ok" else []
    if not charts:
        c = _sql_chart(sql)
        charts = [c] if c else []
    tables = list(an.get("tables", [])) if an and an.get("status") == "ok" else []
    citations = rag["citations"] if rag and rag["status"] == "ok" else []
    final = {
        "answer": answer, "llm_used": llm_used,
        "route": {"tools": state.get("plan", []), "reason": state.get("route_reason", ""),
                  "standalone_question": state.get("standalone", "")},
        "sql": sql_for_api(sql), "charts": charts, "tables": tables, "citations": citations,
        "external": ({"status": rs["status"], "message": rs.get("message", ""), "results": rs.get("results", [])}
                     if rs else None),
        "definitions": an.get("definitions", []) if an and an.get("status") == "ok" else [],
        "bullets": an.get("bullets", []) if an and an.get("status") == "ok" else [],
        "metrics": an.get("metrics", {}) if an and an.get("status") == "ok" else {},
        "analytics_intent": an.get("intent") if an and an.get("status") == "ok" else None,
        "rag": ({"status": rag["status"], "coverage": rag["coverage"], "queries": rag["queries"],
                 "timings_ms": rag["timings_ms"]} if rag else None),
        "verification": state.get("verification", {}), "needs_approval": state.get("needs_approval", []),
        "warnings": warnings, "steps": state.get("steps", []),
    }
    return {"final": final}


# ----------------------------------------------------------------------------- graph
def build_graph():
    g = StateGraph(GraphState)
    g.add_node("analyze", analyze)
    g.add_node("router", router)
    g.add_node("sql_agent", sql_agent)
    g.add_node("analytics_agent", analytics_agent)
    g.add_node("rag_agent", rag_agent)
    g.add_node("research_agent", research_agent)
    g.add_node("verify", verify)
    g.add_node("respond", respond)
    g.set_entry_point("analyze")
    g.add_edge("analyze", "router")
    targets = {**{n: n for n in NODE_BY_TOOL.values()}, "verify": "verify"}
    g.add_conditional_edges("router", pick_next, targets)
    for node in NODE_BY_TOOL.values():
        g.add_edge(node, "router")
    g.add_conditional_edges("verify", after_verify, {"rag_agent": "rag_agent", "respond": "respond"})
    g.add_edge("respond", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_question(db, user, question: str, *, history: list[dict] | None = None, allow_external: bool = False,
                 category: str | None = None, department: str | None = None,
                 force_tools: list[str] | None = None, llm=None) -> dict:
    """Run the full workflow and return the final response dict (never raises for tool failures)."""
    llm = llm or get_llm()
    state: GraphState = {"question": question, "history": history or [], "allow_external": allow_external,
                         "category": category, "department": department, "force_tools": force_tools,
                         "steps": [], "warnings": []}
    out = get_graph().invoke(state, config={"configurable": {"db": db, "user": user, "llm": llm},
                                            "recursion_limit": 40})
    return out["final"]
