from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.models import (
    CaregiverInvitation,
    CaregiverLink,
    ChatSession,
    Consent,
    ConsentHistory,
    SessionAnalysis,
    User,
)
from app.schemas import ConsentUpdateIn, ReminderSettingsIn, UserBootstrapIn, UserOut, UserUpdateIn

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def ensure_consent(db: Session, user: User) -> Consent:
    if user.consent is None:
        user.consent = Consent(user_id=user.id)
        db.add(user.consent)
        db.flush()
    return user.consent


@router.post("/bootstrap", response_model=UserOut)
def bootstrap(payload: UserBootstrapIn, db: DbSession) -> User:
    user = db.scalar(select(User).where(User.device_id == payload.device_id))
    if user is None:
        user = User(device_id=payload.device_id, display_name=payload.display_name)
        db.add(user)
        db.flush()
    elif user.display_name != payload.display_name:
        user.display_name = payload.display_name
    ensure_consent(db, user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def get_me(user: CurrentUser, db: DbSession) -> User:
    ensure_consent(db, user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdateIn, user: CurrentUser, db: DbSession) -> User:
    user.display_name = payload.display_name
    ensure_consent(db, user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/me/consents", response_model=UserOut)
def update_consents(payload: ConsentUpdateIn, user: CurrentUser, db: DbSession) -> User:
    db.execute(select(User).where(User.id == user.id).with_for_update())
    consent = ensure_consent(db, user)
    consent.analysis_allowed = payload.analysis_allowed
    consent.caregiver_share_allowed = payload.caregiver_share_allowed
    consent.share_medication = payload.share_medication and payload.caregiver_share_allowed
    consent.share_mood = (
        payload.share_mood and payload.analysis_allowed and payload.caregiver_share_allowed
    )
    consent.share_language = (
        payload.share_language and payload.analysis_allowed and payload.caregiver_share_allowed
    )
    consent.onboarding_completed = payload.onboarding_completed
    consent.updated_at = datetime.now(UTC)
    db.add(
        ConsentHistory(
            user_id=user.id,
            values={
                key: getattr(consent, key)
                for key in (
                    "analysis_allowed",
                    "caregiver_share_allowed",
                    "share_medication",
                    "share_mood",
                    "share_language",
                    "onboarding_completed",
                )
            },
        )
    )
    if not consent.analysis_allowed:
        db.execute(delete(SessionAnalysis).where(SessionAnalysis.user_id == user.id))
        db.execute(
            update(ChatSession)
            .where(ChatSession.user_id == user.id)
            .values(
                analysis_consent_snapshot=False,
            )
        )
    if not consent.caregiver_share_allowed:
        db.execute(delete(CaregiverLink).where(CaregiverLink.owner_id == user.id))
        db.execute(delete(CaregiverInvitation).where(CaregiverInvitation.owner_id == user.id))
    db.commit()
    db.refresh(user)
    return user


@router.put("/me/reminders", response_model=UserOut)
def update_reminders(payload: ReminderSettingsIn, user: CurrentUser, db: DbSession):
    if (
        payload.chat_reminder_at.tzinfo is not None
        or payload.chat_reminder_at.second
        or payload.chat_reminder_at.microsecond
    ):
        raise AppError(422, "INVALID_REMINDER_TIME", "한국 시간 기준 시와 분을 입력해주세요.")
    user.chat_reminder_enabled = payload.chat_reminder_enabled
    user.chat_reminder_at = payload.chat_reminder_at
    db.commit()
    return user
