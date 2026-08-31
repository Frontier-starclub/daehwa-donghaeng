from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    device_id: Annotated[str | None, Header(alias="X-Device-ID")] = None,
) -> User:
    if not device_id:
        raise AppError(401, "DEVICE_ID_REQUIRED", "X-Device-ID 헤더가 필요합니다.")
    user = db.scalar(select(User).where(User.device_id == device_id))
    if user is None:
        raise AppError(
            401,
            "DEVICE_NOT_REGISTERED",
            "먼저 사용자 bootstrap을 완료해주세요.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
