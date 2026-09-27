"""Consent-gated, structured observations; no clinical diagnosis or shared text."""

import re
from datetime import UTC, datetime, timedelta
from statistics import mean

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.models import ChatSession, SessionAnalysis, User
from app.providers import _HttpProvider


class MoodResult(BaseModel):
    mood_score: float = Field(ge=-1, le=1, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


def analyze_session(session: ChatSession, user: User, db) -> SessionAnalysis | None:
    db.execute(select(User).where(User.id == user.id).with_for_update())
    db.refresh(user, ["consent"])
    db.refresh(session, ["analysis_consent_snapshot", "status"])
    if (
        session.status != "ended"
        or not session.analysis_consent_snapshot
        or not user.consent
        or not user.consent.analysis_allowed
    ):
        return None
    existing = db.get(SessionAnalysis, session.id)
    if existing and existing.status == "complete":
        return existing
    texts = [message.content for message in session.messages if message.role == "user"]
    if not texts:
        return None
    words = re.findall(r"[가-힣A-Za-z0-9]+", " ".join(texts).lower())
    metrics = {
        "utterance_count": len(texts),
        "mean_characters": round(mean(len(text.strip()) for text in texts), 2),
        "vocabulary_diversity": round(len(set(words)) / len(words), 4) if words else 0,
        "mood_score": None,
        "mood_confidence": None,
    }
    settings = get_settings()
    record = existing or SessionAnalysis(session_id=session.id, user_id=user.id)
    record.provider = settings.provider_mode
    record.status = "complete"
    record.error_code = None
    try:
        if settings.provider_mode == "remote":
            result = _HttpProvider(str(settings.ai_service_url), settings.ai_service_timeout)._post(
                "/v1/analysis/session",
                MoodResult,
                json={"utterances": texts[-30:]},
            )
            metrics.update(mood_score=result.mood_score, mood_confidence=result.confidence)
        else:
            metrics.update(mood_score=0.0, mood_confidence=0.0)
    except RuntimeError:
        record.status = "partial"
        record.error_code = "ANALYSIS_PROVIDER_ERROR"
    record.metrics = metrics
    db.add(record)
    db.commit()
    return record


def _window(rows):
    values = [row.metrics for row in rows if row.metrics]
    mood = [
        item["mood_score"]
        for item in values
        if item.get("mood_score") is not None and item.get("mood_confidence", 0) >= 0.5
    ]
    utterances = sum(item["utterance_count"] for item in values)
    return {
        "sessions": len(values),
        "utterances": utterances,
        "sufficient": len(values) >= 3 and utterances >= 10,
        "mood_sessions": len(mood),
        "mood_score": round(mean(mood), 3) if mood else None,
        "mean_characters": round(mean(item["mean_characters"] for item in values), 2)
        if values
        else None,
        "vocabulary_diversity": round(mean(item["vocabulary_diversity"] for item in values), 3)
        if values
        else None,
    }


def build_insights(user_id, db):
    now = datetime.now(UTC)
    split = now - timedelta(days=7)
    since = now - timedelta(days=14)
    rows = db.execute(
        select(SessionAnalysis, ChatSession.ended_at)
        .join(ChatSession)
        .where(
            SessionAnalysis.user_id == user_id,
            ChatSession.ended_at >= since,
        )
    ).all()
    current, previous = [], []
    for row, ended in rows:
        ended = ended.replace(tzinfo=UTC) if ended.tzinfo is None else ended
        (current if ended >= split else previous).append(row)
    current_window, previous_window = _window(current), _window(previous)
    sufficient = current_window["sufficient"] and previous_window["sufficient"]
    delta = {}
    if sufficient:
        for key in ("mean_characters", "vocabulary_diversity", "mood_score"):
            left, right = current_window[key], previous_window[key]
            if (
                key == "mood_score"
                and min(current_window["mood_sessions"], previous_window["mood_sessions"]) < 3
            ):
                continue
            if left is not None and right is not None:
                delta[key] = round(left - right, 3)
    return {
        "period_days": 7,
        "minimum_sessions": 3,
        "minimum_utterances": 10,
        "status": "comparable" if sufficient else "collecting",
        "current": current_window,
        "previous": previous_window,
        "change": delta,
        "partial_sessions": sum(row.status != "complete" for row, _ in rows),
        "has_demo_data": any(row.provider == "mock" for row, _ in rows),
        "disclaimer": "대화 기록의 변화이며 건강 상태나 인지 기능을 진단하는 결과가 아닙니다.",
    }
