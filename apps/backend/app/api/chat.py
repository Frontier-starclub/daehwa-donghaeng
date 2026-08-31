import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.models import ChatMessage, ChatSession
from app.providers import chat_provider
from app.schemas import (
    ChatMessageIn,
    ChatSessionCreateIn,
    ChatSessionOut,
    ChatTurnOut,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def get_owned_session(
    db: DbSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> ChatSession:
    session = db.scalar(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    )
    if session is None:
        raise AppError(404, "CHAT_SESSION_NOT_FOUND", "대화 세션을 찾을 수 없습니다.")
    return session


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
def create_session(
    payload: ChatSessionCreateIn, user: CurrentUser, db: DbSession
) -> ChatSession:
    active = db.scalar(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.user_id == user.id, ChatSession.status == "active")
        .order_by(ChatSession.started_at.desc())
    )
    if active is not None:
        if payload.decision == "accepted":
            return active
        raise AppError(409, "ACTIVE_CHAT_EXISTS", "진행 중인 대화를 먼저 종료해주세요.")

    consent_allowed = bool(user.consent and user.consent.analysis_allowed)
    now = datetime.now(UTC)
    session = ChatSession(
        user_id=user.id,
        status="active" if payload.decision == "accepted" else "declined",
        analysis_consent_snapshot=consent_allowed,
        started_at=now,
        ended_at=None if payload.decision == "accepted" else now,
        last_activity_at=now,
    )
    db.add(session)
    db.flush()
    if payload.decision == "accepted":
        session.messages.append(
            ChatMessage(
                role="assistant",
                content=chat_provider.opening_message(),
                sequence_no=1,
            )
        )
    db.commit()
    return get_owned_session(db, user.id, session.id)


@router.get("/sessions/current", response_model=ChatSessionOut | None)
def get_current_session(user: CurrentUser, db: DbSession) -> ChatSession | None:
    return db.scalar(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.user_id == user.id, ChatSession.status == "active")
        .order_by(ChatSession.started_at.desc())
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
def get_session(
    session_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ChatSession:
    return get_owned_session(db, user.id, session_id)


@router.post("/sessions/{session_id}/messages", response_model=ChatTurnOut)
def add_message(
    session_id: uuid.UUID,
    payload: ChatMessageIn,
    user: CurrentUser,
    db: DbSession,
) -> ChatTurnOut:
    session = get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise AppError(409, "CHAT_SESSION_CLOSED", "종료된 대화에는 메시지를 추가할 수 없습니다.")

    existing_user = db.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == session.id,
            ChatMessage.client_message_id == payload.client_message_id,
        )
    )
    if existing_user is not None:
        existing_assistant = db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == session.id,
                ChatMessage.sequence_no == existing_user.sequence_no + 1,
                ChatMessage.role == "assistant",
            )
        )
        if existing_assistant is None:
            raise AppError(409, "CHAT_TURN_INCOMPLETE", "이전 메시지 처리를 다시 시도해주세요.")
        return ChatTurnOut(
            user_message=existing_user,
            assistant_message=existing_assistant,
        )

    max_sequence = db.scalar(
        select(func.max(ChatMessage.sequence_no)).where(
            ChatMessage.session_id == session.id
        )
    ) or 0
    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        content=payload.content,
        sequence_no=max_sequence + 1,
        client_message_id=payload.client_message_id,
    )
    session.user_message_count += 1
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=chat_provider.reply(session.user_message_count, payload.content),
        sequence_no=max_sequence + 2,
    )
    session.last_activity_at = datetime.now(UTC)
    db.add_all([user_message, assistant_message])
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    db.expire(session, ["messages"])
    return ChatTurnOut(
        user_message=user_message,
        assistant_message=assistant_message,
    )


@router.post("/sessions/{session_id}/end", response_model=ChatSessionOut)
def end_session(
    session_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ChatSession:
    session = get_owned_session(db, user.id, session_id)
    if session.status == "declined":
        raise AppError(409, "CHAT_SESSION_DECLINED", "거절 기록은 종료할 수 없습니다.")
    if session.status == "active":
        now = datetime.now(UTC)
        session.status = "ended"
        session.ended_at = now
        session.last_activity_at = now
        db.commit()
    return get_owned_session(db, user.id, session.id)
