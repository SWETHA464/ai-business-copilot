# Architecture

```
React (Vite) SPA  --HTTP/JSON + JWT-->  FastAPI
                                          |
          +-------------------------------+---------------------------------+
          |                |                 |                |             |
      auth/RBAC       chat API        documents API     analytics API   reports API
          |                |                 |                |             |
          |        LangGraph orchestrator    |        pandas analytics      PDF (reportlab)
          |   analyze -> router -> {sql_agent, analytics_agent, rag_agent, research_agent}
          |                          -> verify -> respond
          |                |                 |                |
     SQLAlchemy      LLM provider      RAG engine      read-only engine
   (app database)   (Ollama / hosted / none) FAISS + BM25   (business tables only)
```

## Layers (backend/app)
| Folder | Responsibility |
|---|---|
| `api/` | FastAPI routers: auth, chat, documents, analytics + dashboard, reports, system (health/status) |
| `graph/` | `routing.py` (rule-based tool routing, follow-up condensation), `orchestrator.py` (LangGraph graph) |
| `agents/` | `sql_agent.py`, `rag_agent.py`, `research_agent.py` |
| `tools/` | `sql_guard.py` - sqlglot-based validator |
| `rag/` | extraction, chunking, embeddings, FAISS + BM25 index, retrieval, reranking |
| `services/` | document service, analytics (pandas), LLM abstraction, narrative text, report service, dataset/sample-document generators |
| `security/` | Argon2 + JWT, rate limiting, prompt-injection guard |
| `models/`, `schemas/`, `database/` | ORM models, Pydantic schemas, engines/sessions |

## LangGraph workflow
1. **analyze** - condenses follow-up questions using the conversation (only when the question looks like a follow-up).
2. **router** - picks tools. Rules first (deterministic and testable); the LLM is consulted only if no rule fires, and its answer is validated against the fixed tool whitelist. Dispatches one tool per visit, in the order sql, analytics, rag, external.
3. **sql_agent / analytics_agent / rag_agent / research_agent** - each writes its result into shared state and returns to the router.
4. **verify** - checks that evidence exists for what will be claimed; may trigger one RAG retry.
5. **respond** - builds the answer. Numbers come from SQL/pandas results; the LLM only phrases explanations and is optional (template fallback).

Routing examples: refund policy -> RAG; highest-revenue product -> SQL + analytics; "why did sales decrease, and what do the reports say" -> SQL + analytics + RAG; compare with industry trends -> SQL + analytics + external.

Limits: `MAX_STEPS` = 8 tool dispatches, one RAG retry, per-node error isolation. **Human approval:** external web research runs only when the user explicitly allows it for that message; otherwise the response says approval is needed.

## RAG pipeline
Ingest: validate (type, size, content-based checks such as PDF/DOCX signatures and text decodability) -> extract (PyMuPDF / python-docx / text / pandas) with page numbers -> clean -> chunk (size/overlap configurable) -> embed -> FAISS + BM25 -> persist chunk rows. Chunk IDs are stable and deterministic (derived from document id, content hash and chunk index); duplicates are detected by content hash per owner, so no re-embedding.
Retrieve: access filter (owner/shared/category/department) -> query rewrite (heuristic or LLM) + multi-query -> dense + BM25 -> Reciprocal Rank Fusion (k=60; robust to incomparable score scales) -> cross-encoder rerank -> context selection/compression -> evidence-sufficiency check. Below the coverage threshold the system says the information is not available.
Consistency: `verify_consistency` compares DB chunk rows against FAISS/BM25 sizes and IDs; `rebuild-index` reconstructs both from the DB.
Fallbacks: if sentence-transformers / the cross-encoder cannot be loaded, a deterministic hash embedder and lexical reranker are used and reported in `/api/status`.

## SQL safety
Defence in depth: (1) sqlglot parse; single `SELECT` only; (2) table/column allow-list (`SQL_ALLOWED_TABLES`, customer email excluded); (3) join/length limits and forced `LIMIT`; (4) read-only DB connection (MySQL `readonly_user` with SELECT only, SQLite opened read-only); (5) statement timeout. Credentials are never placed in prompts. Failed validation/execution allows limited correction retries, otherwise the agent explains why it could not run the query.

## Prompt-injection handling
Document passages and web results are wrapped as untrusted data, scanned for instruction-like patterns, and the system prompt states they cannot override policy. This reduces, but cannot eliminate, the risk.
