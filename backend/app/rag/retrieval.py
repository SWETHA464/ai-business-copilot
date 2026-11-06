"""Hybrid retrieval: query rewriting -> multi-query dense + BM25 -> RRF fusion -> metadata/ACL filtering ->
reranking -> evidence check -> context selection/compression.

Everything is parameterised through `RetrievalConfig` so the evaluation script can compare configurations.
Access control: only chunks from `allowed_docs` can ever be returned (the filter is applied inside the index search).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, User
from app.rag.embeddings import get_embedder
from app.rag.index import get_index
from app.rag.rerank import get_reranker
from app.rag.text_utils import sentences, tokenize
from app.services.document_service import accessible_doc_ids
from app.services.llm import LLMUnavailable, extract_json, get_llm
from app.utils.logging import get_logger

log = get_logger("retrieval")

SYNONYMS = {
    "decline": ["decrease", "drop", "fall"], "decrease": ["decline", "drop"], "drop": ["decline", "decrease"],
    "increase": ["growth", "rise"], "growth": ["increase", "rise"], "refund": ["return", "reimbursement"],
    "reason": ["cause", "driver", "because"], "why": ["reason", "cause"], "customer": ["client", "buyer"],
    "revenue": ["sales", "income"], "sales": ["revenue"], "policy": ["rule", "guideline"],
    "strategy": ["plan", "initiative"],
}


@dataclass
class RetrievalConfig:
    top_k: int = 8
    candidates: int = 30
    rrf_k: int = 60
    use_dense: bool = True
    use_bm25: bool = True
    use_rewrite: bool = True
    use_rerank: bool = True
    n_query_variants: int = 3
    context_char_budget: int = 6000
    min_evidence_coverage: float = 0.34

    @classmethod
    def from_settings(cls) -> "RetrievalConfig":
        s = get_settings()
        return cls(top_k=s.retrieval_top_k, candidates=s.retrieval_candidates, rrf_k=s.rrf_k,
                   n_query_variants=s.n_query_variants, context_char_budget=s.context_char_budget,
                   min_evidence_coverage=s.min_evidence_coverage)


@dataclass
class Hit:
    chunk_id: str
    document_id: int
    filename: str
    category: str
    page: int | None
    text: str
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    score: float = 0.0
    compressed: str = ""


@dataclass
class RetrievalResult:
    query: str
    queries: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    sufficient: bool = False
    coverage: float = 0.0
    reason: str = ""
    timings_ms: dict[str, float] = field(default_factory=dict)
    index_size: int = 0
    searched_documents: int = 0


# --------------------------------------------------------------------------- query rewriting
def heuristic_variants(query: str, n: int) -> list[str]:
    toks = list(dict.fromkeys(tokenize(query, drop_stop=True)))
    variants = [query.strip()]
    if toks:
        variants.append(" ".join(toks))
        expanded = list(toks)
        for t in toks:
            for key, syns in SYNONYMS.items():
                if t.startswith(key[:5]) or key.startswith(t[:5]):
                    expanded += [x for x in syns if x not in expanded][:2]
        variants.append(" ".join(dict.fromkeys(expanded)))
    out: list[str] = []
    for v in variants:
        if v and v.lower() not in {o.lower() for o in out}:
            out.append(v)
    return out[:max(n, 1)]


def rewrite_queries(query: str, n: int, llm=None) -> list[str]:
    base = heuristic_variants(query, n)
    llm = llm or get_llm()
    if n <= 1 or not llm.configured():
        return base
    try:
        raw = llm.generate(
            "You rewrite search queries for a business-document search engine. Reply with JSON only: "
            '{"queries": ["...", "..."]}. Produce short alternative phrasings using different keywords. '
            "Never answer the question and never add facts.",
            f"Original query: {query}\nGive {n - 1} alternative queries.", json_mode=True, max_tokens=200)
        obj = extract_json(raw) or {}
        alts = [str(x).strip()[:200] for x in obj.get("queries", []) if isinstance(x, str) and x.strip()]
    except LLMUnavailable:
        return base
    out = [query.strip()]
    for a in alts + base[1:]:
        if a.lower() not in {o.lower() for o in out}:
            out.append(a)
    return out[:n]


# --------------------------------------------------------------------------- fusion + compression
def rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


def compress_text(text: str, query_tokens: set[str], max_chars: int) -> str:
    """Extractive compression: keep the most query-relevant sentences (in original order) within max_chars."""
    if len(text) <= max_chars:
        return text
    sents = sentences(text)
    scored = sorted(range(len(sents)), key=lambda i: (-len(query_tokens & set(tokenize(sents[i]))), i))
    keep: set[int] = set()
    used = 0
    for i in scored:
        if used + len(sents[i]) + 1 > max_chars and keep:
            continue
        keep.add(i)
        used += len(sents[i]) + 1
    return " ".join(sents[i] for i in sorted(keep))[:max_chars]


def _coverage(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & set(tokenize(text))) / len(query_tokens)


# --------------------------------------------------------------------------- main entry
def retrieve(db: Session, query: str, user: User, *, config: RetrievalConfig | None = None,
             category: str | None = None, department: str | None = None,
             document_ids: list[int] | None = None, llm=None) -> RetrievalResult:
    cfg = config or RetrievalConfig.from_settings()
    result = RetrievalResult(query=query)
    t0 = time.perf_counter()
    allowed = accessible_doc_ids(db, user, category=category, department=department, document_ids=document_ids)
    result.searched_documents = len(allowed)
    if not allowed:
        result.reason = "No accessible documents match the filters."
        return result
    index = get_index(db)
    result.index_size = index.size
    if index.size == 0:
        result.reason = "The document index is empty."
        return result

    queries = rewrite_queries(query, cfg.n_query_variants, llm) if cfg.use_rewrite else [query.strip()]
    result.queries = queries
    t1 = time.perf_counter()
    result.timings_ms["rewrite"] = round((t1 - t0) * 1000, 1)

    rankings: list[list[str]] = []
    embedder = get_embedder() if cfg.use_dense else None
    for q in queries:
        if cfg.use_dense and embedder is not None:
            qv = embedder.embed([q])[0]
            rankings.append([cid for cid, _ in index.dense_search(qv, cfg.candidates, allowed)])
        if cfg.use_bm25:
            rankings.append([cid for cid, _ in index.bm25_search(q, cfg.candidates, allowed)])
    fused = rrf_fuse([r for r in rankings if r], cfg.rrf_k)
    t2 = time.perf_counter()
    result.timings_ms["search"] = round((t2 - t1) * 1000, 1)
    if not fused:
        result.reason = "No passages matched the query."
        return result

    ordered = sorted(fused, key=lambda c: -fused[c])[:cfg.candidates]
    rows = {c.id: c for c in index.chunks if c.id in set(ordered)}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({r.document_id for r in rows.values()})))}
    hits = [Hit(chunk_id=cid, document_id=rows[cid].document_id, filename=docs[rows[cid].document_id].filename,
                category=docs[rows[cid].document_id].category, page=rows[cid].page, text=rows[cid].text,
                rrf_score=fused[cid]) for cid in ordered if cid in rows and rows[cid].document_id in docs]

    reranker = get_reranker()
    if cfg.use_rerank and hits:
        scores = reranker.score(query, [h.text for h in hits])
        top_rrf = max(h.rrf_score for h in hits) or 1.0
        for h, sc in zip(hits, scores):
            h.rerank_score = sc
            h.score = 0.75 * sc + 0.25 * (h.rrf_score / top_rrf)
    else:
        top_rrf = max(h.rrf_score for h in hits) or 1.0
        for h in hits:
            h.score = h.rrf_score / top_rrf
    hits.sort(key=lambda h: -h.score)
    hits = hits[:cfg.top_k]
    t3 = time.perf_counter()
    result.timings_ms["rerank"] = round((t3 - t2) * 1000, 1)

    qtoks = set(tokenize(query))
    best_cov = max((_coverage(qtoks, h.text) for h in hits), default=0.0)
    result.coverage = round(best_cov, 3)
    semantic_ok = reranker.name != "lexical" and hits and hits[0].rerank_score >= 0.5
    result.sufficient = bool(hits) and (best_cov >= cfg.min_evidence_coverage or semantic_ok)
    result.reason = "" if result.sufficient else "The documents do not appear to contain information about this."

    per_chunk = max(300, cfg.context_char_budget // max(len(hits), 1))
    for h in hits:
        h.compressed = compress_text(h.text, qtoks, per_chunk)
    result.hits = hits
    result.timings_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
    log.info("retrieval q_variants=%d hits=%d coverage=%.2f sufficient=%s ms=%s", len(queries), len(hits),
             result.coverage, result.sufficient, result.timings_ms)
    return result


def with_config(**changes) -> RetrievalConfig:
    return replace(RetrievalConfig.from_settings(), **changes)
