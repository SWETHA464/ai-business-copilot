"""Test configuration: isolated temp SQLite DB, no network, no LLM, offline embeddings.

Environment must be set BEFORE the app package is imported (settings/engines are created at import).
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="copilot_tests_"))
os.environ.update(
    {
        "APP_ENV": "test",
        "SECRET_KEY": "test-secret-key-not-for-production-use-1234567890",
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "VECTOR_STORE_DIR": str(_TMP / "vector_store"),
        "REPORTS_DIR": str(_TMP / "reports"),
        "LLM_PROVIDER": "none",
        "EMBEDDING_BACKEND": "hash",
        "RERANK_BACKEND": "lexical",
        "TAVILY_API_KEY": "",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "LOGIN_RATE_LIMIT_PER_MINUTE": "100000",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def register_and_login(client, email="user@example.com", password="Passw0rdA", name="Test User"):
    client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth_headers(client):
    return register_and_login(client)
