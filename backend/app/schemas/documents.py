from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: int
    filename: str
    file_type: str
    size_bytes: int
    category: str
    department: str
    visibility: str
    status: str
    error: str | None = None
    page_count: int
    chunk_count: int
    created_at: datetime
    owner_id: int
    can_modify: bool = False


class DocumentDetail(DocumentOut):
    preview: str = ""


class DocumentMetaUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    visibility: str | None = Field(default=None, pattern="^(shared|private)$")


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    category: str | None = None
    department: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHitOut(BaseModel):
    document_id: int
    filename: str
    page: int | None
    category: str
    score: float
    snippet: str


class DocumentSearchResponse(BaseModel):
    query: str
    sufficient_evidence: bool
    hits: list[SearchHitOut]
    queries_used: list[str]
    timings_ms: dict[str, float]


class FilterOptions(BaseModel):
    categories: list[str]
    departments: list[str]
