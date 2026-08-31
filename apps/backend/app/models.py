import uuid
from datetime import UTC, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(50))

    consent: Mapped["Consent | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Consent(Base):
    __tablename__ = "consents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    analysis_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    caregiver_share_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="consent")


class MedicationScan(Base):
    __tablename__ = "medication_scans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30), default="mock")
    scenario: Mapped[str] = mapped_column(String(20), default="success")
    result_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Medication(TimestampMixin, Base):
    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    ingredient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ingredient_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    item_seq: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dose_frequency_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MedicationSchedule(TimestampMixin, Base):
    __tablename__ = "medication_schedules"
    __table_args__ = (
        UniqueConstraint("medication_id", "remind_at", name="uq_schedule_medication_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    medication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    time_slot: Mapped[str] = mapped_column(String(20))
    remind_at: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MedicationEvent(Base):
    __tablename__ = "medication_events"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_at", name="uq_event_schedule_datetime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medication_schedules.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DurCheck(Base):
    __tablename__ = "dur_checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(30), default="mock")
    medication_snapshot: Mapped[list] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    warnings: Mapped[list["DurWarning"]] = relationship(
        back_populates="check", cascade="all, delete-orphan"
    )


class DurWarning(Base):
    __tablename__ = "dur_warnings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    check_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dur_checks.id", ondelete="CASCADE"), index=True
    )
    warning_type: Mapped[str] = mapped_column(String(40))
    medication_ids: Mapped[list] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(Text)
    source_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    check: Mapped[DurCheck] = relationship(back_populates="warnings")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True)
    user_message_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_consent_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.sequence_no"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_no", name="uq_chat_message_sequence"),
        UniqueConstraint("session_id", "client_message_id", name="uq_chat_client_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    sequence_no: Mapped[int] = mapped_column(Integer)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
