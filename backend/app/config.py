"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

_PLACEHOLDER_SECRET = "change-me-generate-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    secret_key: str = _PLACEHOLDER_SECRET
    access_token_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"

    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"
    readonly_database_url: str | None = None
    sql_max_rows: int = 500
    sql_timeout_seconds: int = 10
    sql_max_retries: int = 2

    admin_email: str = "admin@example.com"
    admin_password: str = ""

    llm_provider: str = "ollama"  # ollama | openai_compatible | none
    llm_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: int = 120

    embedding_backend: str = "auto"  # auto | sentence_transformers | hash
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rerank_backend: str = "auto"  # auto | cross_encoder | lexical
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_top_k: int = 8
    retrieval_candidates: int = 30
    rrf_k: int = 60
    min_relevance_score: float = 0.0
    n_query_variants: int = 3
    context_char_budget: int = 6000
    min_evidence_coverage: float = 0.34  # fraction of query terms that must appear in the best chunk

    max_upload_mb: int = 15
    upload_dir: str = str(DATA_DIR / "uploads")
    vector_store_dir: str = str(DATA_DIR / "vector_store")
    reports_dir: str = str(DATA_DIR / "reports")

    tavily_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "ai-business-copilot"

    rate_limit_per_minute: int = 60
    login_rate_limit_per_minute: int = 10

    @field_validator("database_url", "readonly_database_url")
    @classmethod
    def _anchor_sqlite_path(cls, v: str | None) -> str | None:
        """Resolve relative SQLite paths against the repo root so scripts and the server share one file
        no matter which directory they are started from."""
        if v and v.startswith("sqlite:///") and not v.startswith("sqlite:////") and ":memory:" not in v:
            raw = v[len("sqlite:///"):]
            if not (len(raw) > 1 and raw[1] == ":"):  # Windows absolute path like C:/...
                return f"sqlite:///{(REPO_ROOT / raw).resolve().as_posix()}"
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def validate_for_runtime(self) -> list[str]:
        """Return human-readable warnings; raise in production for unsafe config."""
        warnings: list[str] = []
        if self.secret_key == _PLACEHOLDER_SECRET:
            if self.app_env == "production":
                raise RuntimeError("SECRET_KEY must be set in production.")
            warnings.append("SECRET_KEY is the placeholder value; set a random one in .env.")
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
