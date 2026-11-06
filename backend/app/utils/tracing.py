"""Optional LangSmith tracing. Off unless LANGSMITH_TRACING=true and a key is set; never required."""
from __future__ import annotations

import os

from app.config import get_settings
from app.utils.logging import get_logger

log = get_logger("tracing")


def configure_tracing() -> bool:
    s = get_settings()
    if s.langsmith_tracing and s.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
        log.info("LangSmith tracing enabled project=%s", s.langsmith_project)
        return True
    if s.langsmith_tracing:
        log.warning("LANGSMITH_TRACING is true but LANGSMITH_API_KEY is empty; tracing stays off")
    return False
