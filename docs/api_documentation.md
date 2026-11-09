# API documentation

Interactive docs: `http://localhost:8000/docs` (Swagger) and `/redoc`. All endpoints except register, login and health require `Authorization: Bearer <token>`.

| Method | Path | Description |
|---|---|---|
| POST | /api/auth/register | create an **employee** account (admins are created by script) |
| POST | /api/auth/login | returns JWT (rate limited) |
| GET | /api/auth/me | current user |
| POST | /api/chat | ask a question `{message, conversation_id?, allow_external?, category?, department?}` |
| GET | /api/chat/history | list own conversations |
| GET | /api/chat/{id} | conversation with messages (own only) |
| DELETE | /api/chat/{id} | delete own conversation |
| POST | /api/documents/upload | multipart: file, category, department, visibility |
| GET | /api/documents | list visible docs; filters `q`, `category`, `department`, `status` |
| GET | /api/documents/filters | distinct categories/departments |
| POST | /api/documents/search | passage search `{query, category?, department?, top_k?}` |
| GET | /api/documents/{id} | metadata + preview |
| PATCH | /api/documents/{id} | edit category/department/visibility (owner/admin) |
| PUT | /api/documents/{id}/content | replace file content (re-index) |
| POST | /api/documents/{id}/reindex | re-index one document |
| POST | /api/documents/rebuild-index | rebuild FAISS/BM25 from DB (admin) |
| DELETE | /api/documents/{id} | delete file + index entries |
| GET | /api/dashboard/summary | KPIs, monthly revenue, top products, recent activity |
| GET | /api/analytics/revenue | monthly/quarterly/category/region + chart specs |
| GET | /api/analytics/products | product performance; optional `quarter=2026-Q3` |
| GET | /api/analytics/customers | segments, churn, order/payment status |
| POST | /api/analytics/query | pandas-calculated answer to a question |
| POST | /api/reports/generate | `{question, allow_external?}` -> report (stored + PDF) |
| GET | /api/reports | list own reports |
| GET | /api/reports/{id} | report content |
| GET | /api/reports/{id}/download | PDF |
| GET | /api/health | liveness + DB check (no auth) |
| GET | /api/status | configuration/status: DB, LLM, embeddings, reranker, integrations, warnings |

Errors use `{"detail": "..."}`; internal paths, stack traces and credentials are never returned.
