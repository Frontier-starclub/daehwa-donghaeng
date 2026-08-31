import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.models import Medication, MedicationEvent, MedicationSchedule
from app.schemas import (
    MedicationEventOut,
    MedicationEventResponseIn,
    ScheduleOut,
    ScheduleReplaceIn,
)

router = APIRouter(prefix="/api/v1", tags=["medication schedules"])
SEOUL = ZoneInfo("Asia/Seoul")


def get_owned_medication(
    db: DbSession, user_id: uuid.UUID, medication_id: uuid.UUID
) -> Medication:
    medication = db.scalar(
        select(Medication).where(
            Medication.id == medication_id,
            Medication.user_id == user_id,
            Medication.status == "active",
        )
    )
    if medication is None:
        raise AppError(404, "MEDICATION_NOT_FOUND", "활성 약 정보를 찾을 수 없습니다.")
    return medication


@router.put(
    "/medications/{medication_id}/schedules", response_model=list[ScheduleOut]
)
def replace_schedules(
    medication_id: uuid.UUID,
    payload: ScheduleReplaceIn,
    user: CurrentUser,
    db: DbSession,
) -> list[MedicationSchedule]:
    get_owned_medication(db, user.id, medication_id)
    times = [item.remind_at for item in payload.schedules]
    if len(times) != len(set(times)):
        raise AppError(422, "DUPLICATE_REMINDER_TIME", "같은 알림 시각을 중복 설정할 수 없습니다.")

    db.execute(
        delete(MedicationSchedule).where(
            MedicationSchedule.medication_id == medication_id,
            MedicationSchedule.user_id == user.id,
        )
    )
    schedules = [
        MedicationSchedule(
            medication_id=medication_id,
            user_id=user.id,
            time_slot=item.time_slot,
            remind_at=item.remind_at,
        )
        for item in payload.schedules
    ]
    db.add_all(schedules)
    db.commit()
    for schedule in schedules:
        db.refresh(schedule)
    return schedules


def materialize_today_events(user_id: uuid.UUID, db: DbSession) -> None:
    today = datetime.now(SEOUL).date()
    schedules = db.execute(
        select(MedicationSchedule, Medication)
        .join(Medication, Medication.id == MedicationSchedule.medication_id)
        .where(
            MedicationSchedule.user_id == user_id,
            MedicationSchedule.active.is_(True),
            Medication.status == "active",
        )
    ).all()
    changed = False
    for schedule, _ in schedules:
        local_datetime = datetime.combine(today, schedule.remind_at, tzinfo=SEOUL)
        scheduled_at = local_datetime.astimezone(UTC)
        event = db.scalar(
            select(MedicationEvent).where(
                MedicationEvent.schedule_id == schedule.id,
                MedicationEvent.scheduled_at == scheduled_at,
            )
        )
        if event is None:
            db.add(
                MedicationEvent(
                    schedule_id=schedule.id,
                    user_id=user_id,
                    scheduled_at=scheduled_at,
                )
            )
            changed = True
    if changed:
        db.commit()


def event_to_schema(
    event: MedicationEvent,
    schedule: MedicationSchedule,
    medication: Medication,
) -> MedicationEventOut:
    return MedicationEventOut(
        id=event.id,
        schedule_id=schedule.id,
        medication_id=medication.id,
        medication_name=medication.name,
        time_slot=schedule.time_slot,
        remind_at=schedule.remind_at,
        scheduled_at=event.scheduled_at,
        status=event.status,
        responded_at=event.responded_at,
    )


@router.get("/medication-events/today", response_model=list[MedicationEventOut])
def get_today_events(user: CurrentUser, db: DbSession) -> list[MedicationEventOut]:
    materialize_today_events(user.id, db)
    today = datetime.now(SEOUL).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=SEOUL).astimezone(UTC)
    end = datetime.combine(today, datetime.max.time(), tzinfo=SEOUL).astimezone(UTC)
    rows = db.execute(
        select(MedicationEvent, MedicationSchedule, Medication)
        .join(MedicationSchedule, MedicationSchedule.id == MedicationEvent.schedule_id)
        .join(Medication, Medication.id == MedicationSchedule.medication_id)
        .where(
            MedicationEvent.user_id == user.id,
            MedicationEvent.scheduled_at >= start,
            MedicationEvent.scheduled_at <= end,
        )
        .order_by(MedicationEvent.scheduled_at)
    ).all()
    return [event_to_schema(*row) for row in rows]


@router.put(
    "/medication-events/{event_id}/response", response_model=MedicationEventOut
)
def respond_to_event(
    event_id: uuid.UUID,
    payload: MedicationEventResponseIn,
    user: CurrentUser,
    db: DbSession,
) -> MedicationEventOut:
    row = db.execute(
        select(MedicationEvent, MedicationSchedule, Medication)
        .join(MedicationSchedule, MedicationSchedule.id == MedicationEvent.schedule_id)
        .join(Medication, Medication.id == MedicationSchedule.medication_id)
        .where(MedicationEvent.id == event_id, MedicationEvent.user_id == user.id)
    ).first()
    if row is None:
        raise AppError(404, "MEDICATION_EVENT_NOT_FOUND", "복약 일정을 찾을 수 없습니다.")
    event, schedule, medication = row
    event.status = payload.status
    event.responded_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event_to_schema(event, schedule, medication)
