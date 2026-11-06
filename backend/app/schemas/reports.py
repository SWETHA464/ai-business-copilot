from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    allow_external: bool = False
    category: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)


class ReportSummary(BaseModel):
    id: int
    title: str
    question: str
    created_at: datetime
    has_pdf: bool


class ReportDetail(ReportSummary):
    content: dict[str, Any]
