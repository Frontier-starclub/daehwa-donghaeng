import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConsentOut(ApiModel):
    analysis_allowed: bool
    caregiver_share_allowed: bool
    updated_at: datetime


class UserBootstrapIn(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=50)


class UserUpdateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)


class ConsentUpdateIn(BaseModel):
    analysis_allowed: bool
    caregiver_share_allowed: bool


class UserOut(ApiModel):
    id: uuid.UUID
    device_id: str
    display_name: str
    consent: ConsentOut
    created_at: datetime
    updated_at: datetime


class MedicationDraft(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ingredient_name: str | None = Field(default=None, max_length=200)
    ingredient_code: str | None = Field(default=None, max_length=50)
    item_seq: str | None = Field(default=None, max_length=50)
    dose_frequency_per_day: int | None = Field(default=None, ge=1, le=10)
    confidence: float | None = Field(default=None, ge=0, le=1)


class MedicationScanOut(ApiModel):
    id: uuid.UUID
    status: Literal["success", "empty", "failed"]
    provider: str
    items: list[MedicationDraft]
    created_at: datetime


class MedicationBatchIn(BaseModel):
    scan_id: uuid.UUID | None = None
    items: list[MedicationDraft] = Field(min_length=1, max_length=30)


class MedicationUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    ingredient_name: str | None = Field(default=None, max_length=200)
    ingredient_code: str | None = Field(default=None, max_length=50)
    item_seq: str | None = Field(default=None, max_length=50)
    dose_frequency_per_day: int | None = Field(default=None, ge=1, le=10)
    status: Literal["active", "ended"] | None = None


class MedicationOut(ApiModel):
    id: uuid.UUID
    name: str
    ingredient_name: str | None
    ingredient_code: str | None
    item_seq: str | None
    dose_frequency_per_day: int | None
    source: str
    status: str
    confirmed_at: datetime
    ended_at: datetime | None


class DurWarningOut(ApiModel):
    id: uuid.UUID
    warning_type: str
    medication_ids: list[str]
    message: str
    source_code: str | None


class DurCheckIn(BaseModel):
    medication_ids: list[uuid.UUID] | None = None


class DurCheckOut(ApiModel):
    id: uuid.UUID
    status: str
    provider: str
    warnings: list[DurWarningOut]
    checked_at: datetime
    disclaimer: str = "확인 결과는 진단이나 처방이 아닙니다. 의사·약사와 상담하세요."


class ScheduleItemIn(BaseModel):
    time_slot: Literal["morning", "lunch", "dinner", "bedtime", "custom"]
    remind_at: time


class ScheduleReplaceIn(BaseModel):
    schedules: list[ScheduleItemIn] = Field(min_length=1, max_length=8)


class ScheduleOut(ApiModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    time_slot: str
    remind_at: time
    active: bool


class MedicationEventResponseIn(BaseModel):
    status: Literal["taken", "not_taken"]


class MedicationEventOut(ApiModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    medication_id: uuid.UUID
    medication_name: str
    time_slot: str
    remind_at: time
    scheduled_at: datetime
    status: str
    responded_at: datetime | None


class ChatSessionCreateIn(BaseModel):
    decision: Literal["accepted", "declined"]


class ChatMessageIn(BaseModel):
    client_message_id: uuid.UUID
    content: str = Field(min_length=1, max_length=2000)


class ChatMessageOut(ApiModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    sequence_no: int
    client_message_id: uuid.UUID | None
    created_at: datetime


class ChatTurnOut(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut


class ChatSessionOut(ApiModel):
    id: uuid.UUID
    status: Literal["active", "ended", "declined"]
    user_message_count: int
    analysis_consent_snapshot: bool
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    messages: list[ChatMessageOut]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: object | None = None

