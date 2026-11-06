"""FastAPI application entry point."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth as auth_api
from app.api import analytics as analytics_api
from app.api import chat as chat_api
from app.api import documents as documents_api
from app.api import reports as reports_api
from app.api import system as system_api
from app import models as _models  # noqa: F401  (register tables)
from app.config import get_settings
from app.database.session import Base, engine
from app.utils.logging import get_logger, setup_logging
from app.utils.tracing import configure_tracing

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    for w in settings.validate_for_runtime():
        log.warning(w)
    Base.metadata.create_all(engine)
    configure_tracing()
    log.info("application started env=%s", settings.app_env)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Business Intelligence & Research Copilot",
        version="1.0.0",
        description="Hybrid RAG + NL-to-SQL + analytics + LangGraph orchestration.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # pragma: no cover - last-resort guard
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            return JSONResponse({"detail": "Internal server error"}, status_code=500)
        ms = (time.perf_counter() - start) * 1000
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path,
                 response.status_code, ms, rid)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(auth_api.router)
    app.include_router(documents_api.router)
    app.include_router(chat_api.router)
    app.include_router(analytics_api.router)
    app.include_router(reports_api.router)
    app.include_router(system_api.router)
    return app


app = create_app()
