import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.chat import get_owned_session
from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.insights import analyze_session, build_insights
from app.models import ChatSession, SessionAnalysis

router = APIRouter(prefix="/api/v1", tags=["insights"])


@router.get("/insights")
def get_insights(user: CurrentUser, db: DbSession):
    if not user.consent or not user.consent.analysis_allowed:
        raise AppError(403, "ANALYSIS_CONSENT_REQUIRED", "대화 분석 동의 후 이용할 수 있습니다.")
    result = build_insights(user.id, db)
    rows = db.execute(
        select(ChatSession.id, SessionAnalysis.status)
        .outerjoin(SessionAnalysis)
        .where(
            ChatSession.user_id == user.id,
            ChatSession.status == "ended",
            ChatSession.analysis_consent_snapshot.is_(True),
            ChatSession.user_message_count > 0,
        )
        .order_by(ChatSession.ended_at.desc())
        .limit(30)
    ).all()
    result["retry_session_ids"] = [
        str(session_id) for session_id, status in rows if status != "complete"
    ]
    return result


@router.post("/chat/sessions/{session_id}/analysis")
def retry_analysis(session_id: uuid.UUID, user: CurrentUser, db: DbSession):
    session = get_owned_session(db, user.id, session_id)
    record = analyze_session(session, user, db)
    if record is None:
        raise AppError(
            409,
            "ANALYSIS_NOT_AVAILABLE",
            "분석에 동의한 뒤 시작하여 종료한 대화만 분석할 수 있습니다.",
        )
    return {"status": record.status, "error_code": record.error_code}
