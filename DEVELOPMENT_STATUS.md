# Development Status

Last updated: 2026-11-06. Nothing is marked done unless it was actually run (by GitHub Actions CI; the authoring
sandbox cannot reach PyPI/npm, so CI is the verifier).

## Completed and CI-verified (backend, 125+ tests)
- [x] Config, DB session (main + read-only engine), ORM models, auth (Argon2 + JWT), rate limiting
- [x] Synthetic dataset generator, sample documents (PDF/DOCX/TXT/CSV) consistent with the data, analytics (pandas)
- [x] SQL guard (sqlglot) + SQL agent (LLM optional, template fallback), analytics service
- [x] RAG: extraction/validation, chunking, embeddings (sentence-transformers or hash fallback), FAISS + BM25,
      RRF hybrid retrieval, query rewriting, rerank (cross-encoder or lexical fallback), compression, citations
- [x] Document service + API (upload/list/get/search/patch/replace/reindex/delete, ACL, duplicates, rebuild index)
- [x] LangGraph orchestrator, routing, external research agent (Tavily, optional), verification node
- [x] Chat API (conversations, follow-ups), analytics/dashboard API, system health/status API
- [x] Report generation + PDF download

## In progress / remaining
- [~] Frontend (React/Vite/Tailwind): committed so far = Login, Register, Dashboard, Chat, layout, charts, API client, auth context.
      NOT yet written: Documents, Analytics, Reports, History, Settings pages; frontend CI build never run/verified
- [ ] Evaluation (Ragas script, questions.json), docs/, full README
- [ ] Optional: response streaming (not implemented), Redis (not implemented)

## Known limitations
- Authoring sandbox cannot install packages or run the app; real LLM (Ollama), sentence-transformers/cross-encoder,
  MySQL and Tavily were never exercised here. Tests use LLM_PROVIDER=none, hash embeddings, lexical reranker, SQLite.

## Resume
```powershell
git clone https://github.com/SWETHA464/ai-business-copilot
cd ai-business-copilot
# then ask Claude to "continue from DEVELOPMENT_STATUS.md"
```
