"""Health and configuration status. /health is public; /status needs a login. Neither ever returns secrets."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import engine, get_db, get_readonly_engine
from app.models import Document, DocumentChunk, User
from app.rag import index as rag_index
from app.security.auth import get_current_user
from app.services.llm import get_llm

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        ok = False
    return {"status": "ok" if ok else "degraded", "database": "up" if ok else "down",
            "time": datetime.now(timezone.utc).isoformat()}


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    s = get_settings()
    warnings = s.validate_for_runtime()
    biz = {}
    try:
        with get_readonly_engine().connect() as conn:
            for t in ("customers", "products", "orders", "order_items", "payments"):
                biz[t] = int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
        readonly = "ok"
    except Exception:
        readonly, biz = "unavailable", {}
        warnings.append("The read-only business database connection is unavailable.")
    llm = get_llm().health()
    if not llm["reachable"]:
        warnings.append(f"LLM: {llm['detail']}")
    info: dict = {
        "app": {"version": "1.0.0", "environment": s.app_env},
        "database": {"dialect": engine.dialect.name, "readonly_connection": readonly, "business_rows": biz},
        "llm": llm,
        "rag": {"documents": db.scalar(select(func.count(Document.id))) or 0,
                "chunks": db.scalar(select(func.count(DocumentChunk.id))) or 0},
        "integrations": {"external_research": {"configured": bool(s.tavily_api_key),
                                               "detail": "ready" if s.tavily_api_key else
                                               "Set TAVILY_API_KEY to enable web research."},
                         "langsmith": {"enabled": bool(s.langsmith_tracing and s.langsmith_api_key)}},
        "limits": {"max_upload_mb": s.max_upload_mb, "sql_max_rows": s.sql_max_rows,
                   "sql_timeout_seconds": s.sql_timeout_seconds},
        "warnings": warnings,
    }
    try:
        from app.rag.embeddings import get_embedder
        from app.rag.rerank import get_reranker

        info["rag"].update({"embedding_backend": get_embedder().name, "reranker": get_reranker().name})
        if user.role == "admin":
            info["rag"]["index"] = rag_index.verify_consistency(db)
    except Exception:
        info["rag"]["embedding_backend"] = "unavailable"
    return info
