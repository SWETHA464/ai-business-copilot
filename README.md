# AI Business Intelligence & Research Copilot

A local-first business assistant that answers natural-language questions over **structured data** (SQL), **documents** (hybrid RAG) and optionally the **web**, orchestrated by LangGraph, with analytics charts and downloadable PDF reports. It runs entirely on your machine: no Docker, no paid API required.

> Status: locally runnable, **not deployed anywhere**. See [Verification status](#verification-status) for what has and has not been exercised.

## Problem statement
Business information is scattered: sales in a database, policies and quarterly reports in PDFs/DOCX/CSV, market context on the web. Answering "revenue declined last quarter - which products, how does it compare, and do our reports explain why?" normally means writing SQL, doing the maths and reading documents by hand. This app does it in one conversation. **All business numbers come from SQL/pandas calculations, never from the LLM.**

## Features
- JWT auth (Argon2), Admin/Employee roles, per-user conversations, document-level access (shared/private)
- Chat with follow-ups, persistent history, citations (with page numbers), SQL inspection, charts, tables
- Document upload (PDF, DOCX, TXT, CSV), validation, duplicate detection, reindex/replace/delete, index rebuild
- Hybrid RAG: dense (FAISS) + BM25, query rewriting/multi-query, RRF fusion, cross-encoder rerank, compression, "not enough evidence" handling
- NL-to-SQL agent with sqlglot validation, table/column allow-list, read-only connection, row limit, timeout, bounded retries
- pandas analytics: revenue (monthly/quarterly/category/region), product performance, customer segments, churn, KPIs
- LangGraph orchestrator choosing only the tools a question needs; external research (Tavily) behind explicit user approval
- PDF reports that label verified numbers, document evidence, external research and AI recommendations separately
- Evaluation harness (retrieval metrics + optional Ragas), logging, optional LangSmith, health/status endpoints and Settings page

## Technology stack
Frontend: React 18, Vite, Tailwind CSS, React Router, Axios, Recharts, React Markdown.
Backend: Python, FastAPI, Pydantic, SQLAlchemy, Uvicorn, pandas, sqlglot, reportlab.
AI: LangGraph, LangChain core, Ollama (default `llama3.2`) or any OpenAI-compatible API, sentence-transformers, FAISS, rank-bm25, PyMuPDF, python-docx.
Data: MySQL (recommended) or SQLite fallback. Tests: pytest. CI: GitHub Actions.

## Architecture
See [docs/architecture.md](docs/architecture.md), [docs/database_schema.md](docs/database_schema.md), [docs/api_documentation.md](docs/api_documentation.md).

**Workflow:** question -> analyze (resolve follow-ups) -> router -> SQL / analytics / RAG / external agents (as needed) -> verify -> response with citations, SQL, charts.
**RAG pipeline:** extract -> clean -> chunk -> embed -> FAISS + BM25; query -> rewrite -> dense + BM25 -> RRF -> rerank -> select -> grounded answer or "not found".
**LangGraph:** nodes `analyze`, `router`, `sql_agent`, `analytics_agent`, `rag_agent`, `research_agent`, `verify`, `respond`; max 8 tool steps, one RAG retry, approval required for web research.
**Data definitions:** revenue counts completed orders only; churn = completed customer with no completed order in the 90 days before the latest order date.

## Installation (Windows PowerShell)
Prerequisites: Python 3.11+ , Node.js 20+, Git. Optional: MySQL 8, Ollama.

```powershell
git clone https://github.com/SWETHA464/ai-business-copilot
cd ai-business-copilot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
```
Edit `.env`: set `SECRET_KEY` (long random string) and `ADMIN_PASSWORD`. The first run downloads the embedding/reranker models (needs internet once); if they cannot load, the app falls back to hash embeddings and a lexical reranker and says so in Settings.

### Database
**SQLite (default, no setup):** keep `DATABASE_URL=sqlite:///./data/app.db`.
**MySQL:** create the database and users with `docs\mysql_setup.sql` (edit passwords first), then set `DATABASE_URL` and `READONLY_DATABASE_URL` in `.env` (examples inside `.env.example`).

```powershell
python scripts\init_database.py
python scripts\seed_database.py        # synthetic e-commerce data + sample documents
python scripts\create_admin.py         # uses ADMIN_EMAIL / ADMIN_PASSWORD from .env
python scripts\index_documents.py      # index the sample documents for RAG
```
If you use MySQL, run the `GRANT SELECT` statements in `docs\mysql_setup.sql` after `init_database.py`.

### LLM
```powershell
winget install Ollama.Ollama
ollama pull llama3.2
```
`.env`: `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.2`. To use a hosted API: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. `LLM_PROVIDER=none` disables the model: the app still works with template answers and extractive RAG answers.
Optional: `TAVILY_API_KEY` (web research), `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` (tracing).

## Run locally
Terminal 1 (backend):
```powershell
.\.venv\Scripts\Activate.ps1
cd backend
uvicorn app.main:app --reload --port 8000
```
Terminal 2 (frontend):
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173, sign in with the admin account (or register an employee). API docs: http://localhost:8000/docs. Health: `/api/health`; configuration status: Settings page or `/api/status`.

## Testing
```powershell
cd backend
pytest -q
cd ..\frontend
npm run build
```
Backend tests run offline with `LLM_PROVIDER=none`, hash embeddings, lexical reranker and a temporary SQLite database. They cover auth, SQL guard, SQL agent, seed/analytics, document ingestion/RAG/ACL, orchestrator routing, chat, reports/PDF and the evaluation harness. GitHub Actions runs the backend tests and the frontend build on every push.

## Evaluation methodology
`evaluation/questions.json` holds 16 questions (14 answerable with ground truth, key facts and expected source documents; 2 unanswerable). `evaluation/evaluate_rag.py` compares retrieval configurations (BM25 only, dense only, hybrid, + rewrite, + rerank, full) on hit@k, MRR, key-fact recall and abstention accuracy, writing JSON/Markdown to `evaluation/evaluation_results/`. Ragas (faithfulness, answer relevancy, context precision, context recall) is optional:
```powershell
pip install -r evaluation\requirements-eval.txt
python evaluation\evaluate_rag.py --ragas --judge-model llama3.1:8b
```
Small local judge models often cannot produce the structured output Ragas needs; failures are reported, not hidden. **No benchmark scores are published in this README** because none were recorded from a real run yet - run the script and keep your own results.

## Security considerations
Argon2 hashing; JWT; public registration can only create employees; per-user conversations and document ACL enforced inside retrieval; SQL validated with a parser, allow-listed tables/columns, read-only connection, limits and timeout; upload validation (type, size, content) and sanitized stored names; rate limiting; CORS from config; secrets only in `.env`; prompt-injection mitigations for documents and web content; generic error messages. See [docs/architecture.md](docs/architecture.md).

## Verification status
Honest account of what has been run:
- Backend test suite and the frontend build are run by **GitHub Actions CI** (check the Actions tab for the current result). The authoring sandbox had no access to PyPI/npm, so these were not run locally by the author of this code.
- **Never exercised end to end:** real Ollama generation, sentence-transformers / cross-encoder models, MySQL, Tavily, LangSmith, Ragas, and the UI in a browser. These paths are implemented with fallbacks, but expect to fix small integration issues on first run.

## Limitations
Single-process in-memory rate limiting and FAISS index (not for multi-worker deployment); no response streaming; no Redis; SQL generation quality depends on the model (template fallback covers common questions only); sample data is synthetic; prompt-injection defences reduce but do not eliminate risk; Windows is the primary target.

## Future improvements
Response streaming, multi-worker-safe index/rate limiting (Redis), richer report editing, more document formats, human review queue for external research, larger evaluation set and recorded benchmark runs.
