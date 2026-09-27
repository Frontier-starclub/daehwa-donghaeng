import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import select, update

from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.models import Medication, MedicationEvent, MedicationSchedule, User
from app.schemas import (
    MedicationEventOut,
    MedicationEventResponseIn,
    ScheduleOut,
    ScheduleReplaceIn,
)

router = APIRouter(prefix="/api/v1", tags=["medication schedules"])
SEOUL = ZoneInfo("Asia/Seoul")


def get_owned_medication(db: DbSession, user_id: uuid.UUID, medication_id: uuid.UUID) -> Medication:
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


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def lock_user(user_id: uuid.UUID, db: DbSession) -> None:
    db.execute(select(User).where(User.id == user_id).with_for_update())


@router.get("/medications/{medication_id}/schedules", response_model=list[ScheduleOut])
def get_schedules(medication_id: uuid.UUID, user: CurrentUser, db: DbSession):
    get_owned_medication(db, user.id, medication_id)
    return list(
        db.scalars(
            select(MedicationSchedule)
            .where(
                MedicationSchedule.medication_id == medication_id,
                MedicationSchedule.active.is_(True),
            )
            .order_by(MedicationSchedule.remind_at)
        )
    )


@router.get("/medication-schedules", response_model=list[ScheduleOut])
def all_schedules(user: CurrentUser, db: DbSession):
    return list(
        db.scalars(
            select(MedicationSchedule)
            .join(Medication)
            .where(
                MedicationSchedule.user_id == user.id,
                MedicationSchedule.active.is_(True),
                Medication.status == "active",
            )
            .order_by(MedicationSchedule.remind_at)
        )
    )


def deactivate_schedules(schedules, db: DbSession, now: datetime) -> None:
    for schedule in schedules:
        schedule.active = False
        schedule.ended_at = now
        db.execute(
            update(MedicationEvent)
            .where(
                MedicationEvent.schedule_id == schedule.id,
                MedicationEvent.scheduled_at > now,
                MedicationEvent.status == "pending",
            )
            .values(status="cancelled")
        )


@router.put("/medications/{medication_id}/schedules", response_model=list[ScheduleOut])
def replace_schedules(
    medication_id: uuid.UUID,
    payload: ScheduleReplaceIn,
    user: CurrentUser,
    db: DbSession,
) -> list[MedicationSchedule]:
    lock_user(user.id, db)
    get_owned_medication(db, user.id, medication_id)
    times = [item.remind_at for item in payload.schedules]
    if any(value.tzinfo is not None or value.second or value.microsecond for value in times):
        raise AppError(422, "INVALID_REMINDER_TIME", "한국 시간 기준 시와 분을 입력해주세요.")
    if len(times) != len(set(times)):
        raise AppError(422, "DUPLICATE_REMINDER_TIME", "같은 알림 시각을 중복 설정할 수 없습니다.")
    existing = list(
        db.scalars(
            select(MedicationSchedule).where(
                MedicationSchedule.medication_id == medication_id,
                MedicationSchedule.active.is_(True),
            )
        )
    )
    desired = {(item.remind_at, item.time_slot) for item in payload.schedules}
    retained = {
        (item.remind_at, item.time_slot): item
        for item in existing
        if (item.remind_at, item.time_slot) in desired
    }
    deactivate_schedules(
        [item for item in existing if item not in retained.values()], db, datetime.now(UTC)
    )
    schedules = []
    for item in payload.schedules:
        schedule = retained.get((item.remind_at, item.time_slot))
        if schedule is None:
            schedule = MedicationSchedule(
                medication_id=medication_id,
                user_id=user.id,
                time_slot=item.time_slot,
                remind_at=item.remind_at,
            )
            db.add(schedule)
        schedules.append(schedule)
    db.commit()
    return schedules


def materialize_events(user_id: uuid.UUID, db: DbSession, first: date, last: date) -> None:
    lock_user(user_id, db)
    rows = db.execute(
        select(MedicationSchedule, Medication)
        .join(Medication)
        .where(
            MedicationSchedule.user_id == user_id,
        )
    ).all()
    medications_by_schedule = {schedule.id: medication.id for schedule, medication in rows}
    start = datetime.combine(first, datetime.min.time(), tzinfo=SEOUL).astimezone(UTC)
    end = datetime.combine(last, datetime.max.time(), tzinfo=SEOUL).astimezone(UTC)
    existing_events = list(
        db.scalars(
            select(MedicationEvent).where(
                MedicationEvent.user_id == user_id,
                MedicationEvent.scheduled_at >= start,
                MedicationEvent.scheduled_at <= end,
            )
        )
    )
    existing = {(item.schedule_id, aware(item.scheduled_at)) for item in existing_events}
    occupied = {
        (medications_by_schedule[item.schedule_id], aware(item.scheduled_at))
        for item in existing_events
        if item.status != "cancelled"
    }
    for schedule, medication in rows:
        day = max(first, aware(schedule.created_at).astimezone(SEOUL).date())
        ends = [aware(value) for value in (schedule.ended_at, medication.ended_at) if value]
        cutoff = min(ends) if ends else None
        while day <= last:
            when = datetime.combine(day, schedule.remind_at, tzinfo=SEOUL).astimezone(UTC)
            if cutoff is not None and when > cutoff:
                break
            if (schedule.id, when) not in existing and (medication.id, when) not in occupied:
                db.add(MedicationEvent(schedule_id=schedule.id, user_id=user_id, scheduled_at=when))
                existing.add((schedule.id, when))
                occupied.add((medication.id, when))
            day += timedelta(days=1)
    db.flush()


def materialize_today_events(user_id: uuid.UUID, db: DbSession) -> None:
    today = datetime.now(SEOUL).date()
    materialize_events(user_id, db, today, today)
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


def events_between(user_id: uuid.UUID, db: DbSession, first: date, last: date, *, commit=True):
    today = datetime.now(SEOUL).date()
    if last < first or (last - first).days > 92 or last > today:
        raise AppError(422, "INVALID_DATE_RANGE", "오늘까지 최대 93일의 기록을 조회할 수 있습니다.")
    materialize_events(user_id, db, first, last)
    start = datetime.combine(first, datetime.min.time(), tzinfo=SEOUL).astimezone(UTC)
    end = datetime.combine(last, datetime.max.time(), tzinfo=SEOUL).astimezone(UTC)
    rows = db.execute(
        select(MedicationEvent, MedicationSchedule, Medication)
        .join(MedicationSchedule, MedicationSchedule.id == MedicationEvent.schedule_id)
        .join(Medication, Medication.id == MedicationSchedule.medication_id)
        .where(
            MedicationEvent.user_id == user_id,
            MedicationEvent.scheduled_at >= start,
            MedicationEvent.scheduled_at <= end,
            MedicationEvent.status != "cancelled",
        )
        .order_by(MedicationEvent.scheduled_at)
    ).all()
    if commit:
        db.commit()
    return [event_to_schema(*row) for row in rows]


@router.get("/medication-events/today", response_model=list[MedicationEventOut])
def get_today_events(user: CurrentUser, db: DbSession):
    today = datetime.now(SEOUL).date()
    return events_between(user.id, db, today, today)


@router.get("/medication-events", response_model=list[MedicationEventOut])
def get_history(user: CurrentUser, db: DbSession, start: date, end: date):
    return events_between(user.id, db, start, end)


@router.put("/medication-events/{event_id}/response", response_model=MedicationEventOut)
def respond_to_event(
    event_id: uuid.UUID,
    payload: MedicationEventResponseIn,
    user: CurrentUser,
    db: DbSession,
) -> MedicationEventOut:
    lock_user(user.id, db)
    row = db.execute(
        select(MedicationEvent, MedicationSchedule, Medication)
        .join(MedicationSchedule, MedicationSchedule.id == MedicationEvent.schedule_id)
        .join(Medication, Medication.id == MedicationSchedule.medication_id)
        .where(MedicationEvent.id == event_id, MedicationEvent.user_id == user.id)
    ).first()
    if row is None:
        raise AppError(404, "MEDICATION_EVENT_NOT_FOUND", "복약 일정을 찾을 수 없습니다.")
    event, schedule, medication = row
    if event.status == "cancelled":
        raise AppError(409, "EVENT_CANCELLED", "취소된 복약 일정입니다.")
    event.status = payload.status
    event.responded_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event_to_schema(event, schedule, medication)
