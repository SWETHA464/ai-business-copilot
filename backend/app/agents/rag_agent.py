"""RAG agent: turn retrieved passages into a grounded, cited answer.

With an LLM: strict grounded prompt + citation validation. Without one (or on failure): an extractive answer built
from the best-matching sentences, so every statement is traceable to a passage.
"""
from __future__ import annotations

import re

from app.rag.retrieval import RetrievalResult
from app.rag.text_utils import sentences, tokenize
from app.security.prompt_guard import UNTRUSTED_NOTICE, neutralize, wrap_untrusted
from app.services.llm import LLMUnavailable, get_llm
from app.utils.logging import get_logger

log = get_logger("rag_agent")
MAX_SOURCES = 5
NOT_FOUND = ("I could not find information about this in the documents you have access to. "
             "Try rephrasing, check the document filters, or upload a relevant document.")

SYSTEM = (
    "You answer questions about a company using ONLY the numbered sources provided. Rules: "
    "(1) Cite every claim with its source number like [1] or [2]. "
    "(2) If the sources do not contain the answer, say exactly that; do not guess or use outside knowledge. "
    "(3) Do not invent numbers, names, dates or page numbers. "
    "(4) Be concise (at most 6 sentences). " + UNTRUSTED_NOTICE
)


def _citation(n: int, hit) -> dict:
    snippet = (hit.compressed or hit.text)[:300]
    return {"id": n, "document_id": hit.document_id, "filename": hit.filename, "page": hit.page,
            "category": hit.category, "snippet": snippet, "score": round(hit.score, 3)}


QUANT_CUES = re.compile(r"\b(how (long|many|much|often|soon)|when|what (is|was|are) the (rate|amount|limit|window|"
                        r"threshold|percentage|number|total|deadline))\b", re.I)


def extractive_answer(question: str, retrieval: RetrievalResult, max_sentences: int = 3) -> tuple[str, list[int]]:
    """Pick the best distinct, informative sentences. Title-like fragments and duplicates across near-identical
    documents are skipped; numeric sentences are favoured for quantitative questions."""
    qt = set(tokenize(question))
    quant = bool(QUANT_CUES.search(question)) or "window" in qt
    seen: set[str] = set()
    cands = []
    for n, hit in enumerate(retrieval.hits[:MAX_SOURCES], start=1):
        clean, _ = neutralize(hit.text)
        for i, sent in enumerate(sentences(clean)):
            key = " ".join(tokenize(sent))
            if len(sent) < 40 or key in seen:
                continue
            seen.add(key)
            ov = len(qt & set(tokenize(sent)))
            if ov == 0:
                continue
            bonus = 0.75 if quant and any(ch.isdigit() for ch in sent) else 0.0
            cands.append((ov + bonus, -n, -i, sent, n))
    cands.sort(reverse=True)
    picked = cands[:max_sentences]
    if not picked:
        return "", []
    picked.sort(key=lambda c: (c[4], -c[2]))
    used = sorted({c[4] for c in picked})
    text = " ".join(f"{c[3].rstrip()} [{c[4]}]" for c in picked)
    return text, used


def answer(question: str, retrieval: RetrievalResult, llm=None) -> dict:
    llm = llm or get_llm()
    out = {"status": "ok", "answer": "", "citations": [], "used_llm": False}
    if not retrieval.hits or not retrieval.sufficient:
        return {**out, "status": "insufficient_evidence", "answer": f"{NOT_FOUND}"}
    hits = retrieval.hits[:MAX_SOURCES]
    all_cites = {i: _citation(i, h) for i, h in enumerate(hits, start=1)}

    text, used = "", []
    if llm.configured():
        blocks = []
        for i, h in enumerate(hits, start=1):
            page = f", page {h.page}" if h.page else ""
            blocks.append(wrap_untrusted(f"Source [{i}] {h.filename}{page}", h.compressed or h.text))
        prompt = f"Question: {question}\n\nSources:\n" + "\n".join(blocks) + "\n\nAnswer with citations."
        try:
            raw = llm.generate(SYSTEM, prompt, temperature=0.1, max_tokens=500).strip()
            nums = [int(n) for n in re.findall(r"\[(\d{1,2})\]", raw)]
            valid = {n for n in nums if n in all_cites}
            raw = re.sub(r"\[(\d{1,2})\]", lambda m: m.group(0) if int(m.group(1)) in all_cites else "", raw)
            if raw:
                text, used, out["used_llm"] = raw, sorted(valid) or [1], True
        except LLMUnavailable:
            log.info("llm unavailable for rag answer; using extractive fallback")
    if not text:
        text, used = extractive_answer(question, retrieval)
        if not text:
            return {**out, "status": "insufficient_evidence", "answer": NOT_FOUND}
    out["answer"] = text
    out["citations"] = [all_cites[i] for i in used if i in all_cites]
    return out
