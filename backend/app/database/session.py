"""SQLAlchemy engines and sessions.

Two engines exist:
  * the main read/write engine used by the API and ORM models;
  * a read-only engine used exclusively by the NL-to-SQL agent.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path(url: str) -> Path:
    # sqlite:///relative/or/absolute
    return Path(url.replace("sqlite:///", "", 1))


def _make_main_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = _sqlite_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):  # enforce foreign keys in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


_settings = get_settings()
engine: Engine = _make_main_engine(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_ro_lock = threading.Lock()
_ro_engine: Engine | None = None


def make_readonly_engine(main_url: str, readonly_url: str | None) -> Engine:
    """Build a read-only engine. Separate function so tests can build their own."""
    if readonly_url:
        return create_engine(readonly_url, pool_pre_ping=True)
    if main_url.startswith("sqlite"):
        path = _sqlite_path(main_url).resolve()

        def _creator() -> sqlite3.Connection:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            conn.execute("PRAGMA query_only=ON")
            return conn

        return create_engine("sqlite://", creator=_creator, poolclass=NullPool)
    raise RuntimeError(
        "Set READONLY_DATABASE_URL to a MySQL user that only has SELECT privileges."
    )


def get_readonly_engine() -> Engine:
    global _ro_engine
    with _ro_lock:
        if _ro_engine is None:
            s = get_settings()
            _ro_engine = make_readonly_engine(s.database_url, s.readonly_database_url)
        return _ro_engine


def reset_readonly_engine() -> None:
    global _ro_engine
    with _ro_lock:
        if _ro_engine is not None:
            _ro_engine.dispose()
        _ro_engine = None


def apply_query_timeout(dbapi_conn, dialect_name: str, seconds: int) -> None:
    """Best-effort per-connection timeout for the read-only engine."""
    if dialect_name == "sqlite":
        deadline = time.monotonic() + seconds

        def _abort() -> int:
            return 1 if time.monotonic() > deadline else 0

        dbapi_conn.set_progress_handler(_abort, 10000)
    elif dialect_name == "mysql":
        cur = dbapi_conn.cursor()
        cur.execute(f"SET SESSION MAX_EXECUTION_TIME={int(seconds) * 1000}")
        cur.close()
