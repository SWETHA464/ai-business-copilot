# Database schema

SQLAlchemy models in `backend/app/models/models.py`. MySQL is recommended; SQLite is the zero-setup fallback.

| Table | Purpose | Key columns / constraints |
|---|---|---|
| users | accounts | `email` unique; `role` CHECK in (admin, employee); Argon2 hash |
| customers | business | name, email, region, signup_date |
| products | business | sku, name, category, unit_price, cost |
| orders | business | customer_id FK, order_date (indexed), `status` CHECK in (completed, pending, cancelled, refunded), channel |
| order_items | business | order_id FK, product_id FK, quantity, unit_price, discount |
| payments | business | order_id FK, amount, method, status, paid_at |
| documents | uploaded files | owner_id FK; `stored_name` unique and never exposed; content_hash; visibility CHECK (shared/private); status; UNIQUE(owner_id, content_hash) |
| document_chunks | RAG chunk metadata | document_id FK (cascade delete); stable chunk id; page; text |
| conversations | chat threads | user_id FK; title; timestamps |
| messages | chat messages | conversation_id FK; role; content; `meta` JSON (SQL, citations, charts) |
| reports | generated reports | user_id FK; question; content JSON; `pdf_name` (internal file name, never exposed) |

## Metric definitions (used everywhere)
* **Revenue** = as defined in `analytics_service.REVENUE_DEFINITION`: only orders with status `completed` count (sum of quantity x unit_price - discount per item). Pending, cancelled and refunded orders are excluded.
* **Churn** = a customer with at least one completed order but none in the 90 days before the reference date (the latest order date in the data) - see `analytics_service.CHURN_DEFINITION`.
* **Segments** = rule-based customer segments computed in `analytics_service.segment_customers` (the definition text is returned with the results).

## SQL agent access
Only customers (without `email`), products, orders, order_items and payments are queryable by the SQL agent. `users`, `documents`, `conversations`, `messages`, `reports` are not exposed. `docs/mysql_setup.sql` creates the MySQL read-only user with SELECT on those five tables.

## Synthetic data
`backend/app/services/seed_data.py` generates deterministic data (seed 42; 600 customers; Oct 2025 - Sep 2026) with a built-in story (spring promotion in Q2, Wireless Earbuds Pro demand loss and Smart Home Hub supply shortages in Q3). `sample_documents.py` derives all document figures from the same computed data, so documents and SQL agree.
