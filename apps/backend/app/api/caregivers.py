"""One-use invitations and live, consent-filtered reports. No transcript access."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import delete, or_, select

from app.api.schedules import SEOUL, aware, events_between
from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.insights import build_insights
from app.models import CaregiverInvitation, CaregiverLink, User
from app.schemas import CaregiverAcceptIn

router = APIRouter(prefix="/api/v1/caregivers", tags=["caregivers"])


@router.post("/invitations", status_code=201)
def invite(user: CurrentUser, db: DbSession):
    db.execute(select(User).where(User.id == user.id).with_for_update())
    if not user.consent or not user.consent.caregiver_share_allowed:
        raise AppError(403, "SHARING_CONSENT_REQUIRED", "보호자 공유 동의 후 초대할 수 있습니다.")
    # Creating a new invitation invalidates previous unaccepted codes.
    db.execute(delete(CaregiverInvitation).where(CaregiverInvitation.owner_id == user.id))
    code = secrets.token_urlsafe(24)
    expires = datetime.now(UTC) + timedelta(hours=24)
    db.add(
        CaregiverInvitation(
            owner_id=user.id,
            token_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=expires,
        )
    )
    db.commit()
    return {"code": code, "expires_at": expires}


@router.post("/accept", status_code=201)
def accept(payload: CaregiverAcceptIn, user: CurrentUser, db: DbSession):
    invite = db.scalar(
        select(CaregiverInvitation).where(
            CaregiverInvitation.token_hash
            == hashlib.sha256(payload.code.strip().encode()).hexdigest(),
        )
    )
    # All sharing operations lock the owner first, then re-read the invitation.
    # This serializes consent withdrawal, replacement and simultaneous accepts.
    if invite is not None:
        db.execute(select(User).where(User.id == invite.owner_id).with_for_update())
        invite = db.scalar(
            select(CaregiverInvitation)
            .where(CaregiverInvitation.id == invite.id)
            .execution_options(populate_existing=True)
        )
    now = datetime.now(UTC)
    if invite is None or invite.used_at or aware(invite.expires_at) <= now:
        raise AppError(404, "INVITATION_UNAVAILABLE", "초대 코드가 만료되었거나 이미 사용됐습니다.")
    if invite.owner_id == user.id:
        raise AppError(422, "SELF_INVITATION", "다른 기기의 보호자에게 초대 코드를 전달해주세요.")
    owner = db.scalar(select(User).where(User.id == invite.owner_id).with_for_update())
    if owner is None or not owner.consent or not owner.consent.caregiver_share_allowed:
        raise AppError(403, "SHARING_DISABLED", "사용자가 공유를 중단했습니다.")
    link = db.scalar(
        select(CaregiverLink).where(
            CaregiverLink.owner_id == owner.id,
            CaregiverLink.caregiver_id == user.id,
        )
    )
    if link is None:
        link = CaregiverLink(owner_id=owner.id, caregiver_id=user.id)
        db.add(link)
    invite.used_at = now
    db.commit()
    return {"id": str(link.id), "display_name": owner.display_name}


@router.get("/links")
def links(user: CurrentUser, db: DbSession):
    rows = db.scalars(
        select(CaregiverLink)
        .where(
            or_(
                CaregiverLink.owner_id == user.id,
                CaregiverLink.caregiver_id == user.id,
            )
        )
        .order_by(CaregiverLink.created_at)
    )
    result = []
    for link in rows:
        is_owner = link.owner_id == user.id
        other = db.get(User, link.caregiver_id if is_owner else link.owner_id)
        result.append(
            {
                "id": str(link.id),
                "display_name": other.display_name,
                "role": "owner" if is_owner else "caregiver",
            }
        )
    return result


@router.delete("/links/{link_id}", status_code=204)
def revoke(link_id: uuid.UUID, user: CurrentUser, db: DbSession):
    link = db.scalar(
        select(CaregiverLink).where(
            CaregiverLink.id == link_id,
            or_(
                CaregiverLink.owner_id == user.id,
                CaregiverLink.caregiver_id == user.id,
            ),
        )
    )
    if link is None:
        raise AppError(404, "LINK_NOT_FOUND", "연결을 찾을 수 없습니다.")
    db.execute(select(User).where(User.id == link.owner_id).with_for_update())
    db.delete(link)
    db.commit()


def report_for(owner: User, db: DbSession):
    consent = owner.consent
    if not consent or not consent.caregiver_share_allowed:
        raise AppError(403, "SHARING_DISABLED", "사용자가 공유를 중단했습니다.")
    result = {
        "display_name": owner.display_name,
        "generated_at": datetime.now(UTC),
        "medication": None,
        "mood": None,
        "language": None,
        "disclaimer": "기록에 기반한 참고 정보이며 진단이나 처방이 아닙니다.",
    }
    if consent.share_medication:
        today = datetime.now(SEOUL).date()
        events = events_between(owner.id, db, today - timedelta(days=6), today, commit=False)
        now = datetime.now(UTC)
        # Future doses do not count as missed; past pending doses remain in the denominator.
        due = [
            event
            for event in events
            if aware(event.scheduled_at) <= now or event.status in ("taken", "not_taken")
        ]
        taken = sum(event.status == "taken" for event in due)
        result["medication"] = {
            "period_days": 7,
            "scheduled": len(due),
            "taken": taken,
            "not_taken": sum(event.status == "not_taken" for event in due),
            "unanswered": sum(event.status == "pending" for event in due),
            "confirmation_rate": round(taken / len(due), 3) if due else None,
        }
    if consent.analysis_allowed and (consent.share_mood or consent.share_language):
        insights = build_insights(owner.id, db)
        for field, allowed, metrics in (
            ("mood", consent.share_mood, ("mood_score", "mood_sessions")),
            ("language", consent.share_language, ("mean_characters", "vocabulary_diversity")),
        ):
            if allowed:
                result[field] = {
                    "status": insights["status"],
                    "has_demo_data": insights["has_demo_data"],
                    "current": {key: insights["current"][key] for key in metrics},
                    "previous": {key: insights["previous"][key] for key in metrics},
                    "change": {
                        key: value for key, value in insights["change"].items() if key in metrics
                    },
                }
    return result


@router.get("/report-preview")
def preview(user: CurrentUser, db: DbSession):
    db.execute(select(User).where(User.id == user.id).with_for_update())
    result = report_for(user, db)
    db.commit()
    return result


@router.get("/links/{link_id}/report")
def report(link_id: uuid.UUID, user: CurrentUser, db: DbSession):
    link = db.scalar(
        select(CaregiverLink).where(
            CaregiverLink.id == link_id,
            CaregiverLink.caregiver_id == user.id,
        )
    )
    if link is None:
        raise AppError(404, "LINK_NOT_FOUND", "접근 가능한 연결이 없습니다.")
    owner = db.scalar(select(User).where(User.id == link.owner_id).with_for_update())
    # The link could have been revoked while this request waited for the lock.
    if db.scalar(select(CaregiverLink.id).where(CaregiverLink.id == link_id)) is None:
        raise AppError(404, "LINK_NOT_FOUND", "접근 가능한 연결이 없습니다.")
    result = report_for(owner, db)
    db.commit()
    return result
