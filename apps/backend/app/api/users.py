from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser, DbSession
from app.models import Consent, User
from app.schemas import ConsentUpdateIn, UserBootstrapIn, UserOut, UserUpdateIn

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
def update_consents(
    payload: ConsentUpdateIn, user: CurrentUser, db: DbSession
) -> User:
    consent = ensure_consent(db, user)
    consent.analysis_allowed = payload.analysis_allowed
    consent.caregiver_share_allowed = payload.caregiver_share_allowed
    db.commit()
    db.refresh(user)
    return user

