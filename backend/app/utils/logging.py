"""Central logging setup. Never log secrets, passwords or document contents."""
from __future__ import annotations

import logging
import re
import sys

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|password|secret|token)\s*[=:]\s*\S+", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
]


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for pat in _SECRET_PATTERNS:
            msg = pat.sub("[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(root, "_copilot_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
    )
    handler.addFilter(RedactFilter())
    root.addHandler(handler)
    root.setLevel(level)
    root._copilot_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"copilot.{name}")
