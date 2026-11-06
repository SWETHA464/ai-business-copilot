from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None
    allow_external: bool = False
    category: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    meta: dict[str, Any] | None = None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: int
    title: str
    message: ChatMessageOut


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageOut]
