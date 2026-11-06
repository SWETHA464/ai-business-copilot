from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.graph.orchestrator import run_question
from app.models import Conversation, Message, User
from app.schemas.chat import (
    ChatMessageOut, ChatRequest, ChatResponse, ConversationDetail, ConversationSummary,
)
from app.security.auth import get_current_user
from app.security.rate_limit import general_limit
from app.utils.logging import get_logger

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(general_limit)])
log = get_logger("chat")
HISTORY_WINDOW = 6          # previous messages given to the follow-up condenser (this conversation only)


def _owned(db: Session, conv_id: int, user: User) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:     # identical answer for missing and foreign conversations
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _msg(m: Message) -> ChatMessageOut:
    return ChatMessageOut(id=m.id, role=m.role, content=m.content, meta=m.meta, created_at=m.created_at)


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ChatResponse:
    text = body.message.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message must not be empty")
    if body.conversation_id is not None:
        conv = _owned(db, body.conversation_id, user)
    else:
        conv = Conversation(user_id=user.id, title=text[:60])
        db.add(conv)
        db.flush()
    prior = db.scalars(select(Message).where(Message.conversation_id == conv.id)
                       .order_by(Message.id.desc()).limit(HISTORY_WINDOW)).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(prior)]
    db.add(Message(conversation_id=conv.id, role="user", content=text,
                   meta={"allow_external": body.allow_external, "category": body.category,
                         "department": body.department}))
    db.commit()
    try:
        result = run_question(db, user, text, history=history, allow_external=body.allow_external,
                              category=body.category, department=body.department)
    except Exception:
        log.exception("chat workflow failed conv=%s", conv.id)
        db.rollback()
        err = Message(conversation_id=conv.id, role="assistant", content=(
            "Sorry, something went wrong while answering. Your question was saved; please try again."),
            meta={"error": True})
        db.add(err)
        db.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "The assistant hit an unexpected error. Please try again.")
    meta = {k: v for k, v in result.items() if k not in ("answer", "metrics")}
    reply = Message(conversation_id=conv.id, role="assistant", content=result["answer"], meta=meta)
    db.add(reply)
    conv.updated_at = func.now()          # keeps the sidebar ordered by latest activity
    db.commit()
    db.refresh(conv)
    return ChatResponse(conversation_id=conv.id, title=conv.title, message=_msg(reply))


@router.get("/history", response_model=list[ConversationSummary])
def history(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ConversationSummary]:
    counts = dict(db.execute(select(Message.conversation_id, func.count(Message.id))
                             .join(Conversation, Conversation.id == Message.conversation_id)
                             .where(Conversation.user_id == user.id).group_by(Message.conversation_id)).all())
    convs = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                       .order_by(Conversation.updated_at.desc(), Conversation.id.desc())).all()
    return [ConversationSummary(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                                message_count=counts.get(c.id, 0)) for c in convs]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> ConversationDetail:
    conv = _owned(db, conversation_id, user)
    return ConversationDetail(id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at,
                              messages=[_msg(m) for m in conv.messages])


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)) -> None:
    db.delete(_owned(db, conversation_id, user))
    db.commit()
