import uuid
from datetime import UTC, datetime, timedelta

from app.main import app
from app.models import MedicationSchedule, SessionAnalysis
from app.providers import get_chat_provider


def consent(client, headers, **values):
    payload = {
        "analysis_allowed": True,
        "caregiver_share_allowed": True,
        "share_medication": True,
        "share_mood": True,
        "share_language": True,
    }
    payload.update(values)
    response = client.put("/api/v1/users/me/consents", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_context_is_owned_bounded_and_retry_does_not_call_provider(registered_client):
    client, headers = registered_client
    histories = []

    class RecordingChat:
        name = "mock"

        def opening_message(self):
            return "안녕하세요"

        def reply(self, count, content, history=None):
            histories.append(history)
            return "기억하고 있어요"

    app.dependency_overrides[get_chat_provider] = RecordingChat
    session = client.post(
        "/api/v1/chat/sessions", headers=headers, json={"decision": "accepted"}
    ).json()
    path = f"/api/v1/chat/sessions/{session['id']}/messages"
    for i in range(12):
        payload = {"client_message_id": str(uuid.uuid4()), "content": f"제 이야기 {i}"}
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 200
    assert histories[0] == []
    assert len(histories[-1]) == 20
    assert histories[-1][0] == {"role": "user", "content": "제 이야기 1"}
    assert client.post(path, headers=headers, json=payload).json() == response.json()
    assert len(histories) == 12
    payload["content"] = "바뀐 내용"
    assert client.post(path, headers=headers, json=payload).status_code == 409


def test_registration_retries_and_schedule_history(registered_client, db_session):
    client, headers = registered_client
    request_id = str(uuid.uuid4())
    payload = {"request_id": request_id, "items": [{"name": "테스트약"}]}
    first = client.post("/api/v1/medications/batch", headers=headers, json=payload)
    assert first.status_code == 201
    assert (
        client.post("/api/v1/medications/batch", headers=headers, json=payload).json()
        == first.json()
    )
    assert len(client.get("/api/v1/medications", headers=headers).json()) == 1
    assert (
        client.get(f"/api/v1/medication-registrations/{request_id}", headers=headers).json()
        == first.json()
    )
    payload["items"][0]["name"] = "다른 약"
    assert (
        client.post("/api/v1/medications/batch", headers=headers, json=payload).status_code == 409
    )
    med = first.json()[0]["id"]
    path = f"/api/v1/medications/{med}/schedules"
    slots = {"schedules": [{"time_slot": "morning", "remind_at": "08:00:00"}]}
    schedule = client.put(path, headers=headers, json=slots).json()[0]
    row = db_session.get(MedicationSchedule, uuid.UUID(schedule["id"]))
    row.created_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    events = client.get("/api/v1/medication-events/today", headers=headers).json()
    event = events[0]
    client.put(
        f"/api/v1/medication-events/{event['id']}/response",
        headers=headers,
        json={"status": "taken"},
    )
    assert client.put(path, headers=headers, json={"schedules": []}).status_code == 200
    assert client.get(path, headers=headers).json() == []
    assert (
        client.get("/api/v1/medication-events/today", headers=headers).json()[0]["status"]
        == "taken"
    )
    # Re-adding a removed time produces a new schedule without overwriting its history.
    new = client.put(path, headers=headers, json=slots)
    assert new.status_code == 200
    assert new.json()[0]["id"] != schedule["id"]
    after = client.get("/api/v1/medication-events/today", headers=headers).json()
    assert len(after) == 1
    assert after[0]["id"] == event["id"] and after[0]["status"] == "taken"


def test_analysis_and_caregiver_privacy_revocation(registered_client, db_session):
    client, owner = registered_client
    consent(client, owner)
    session = client.post(
        "/api/v1/chat/sessions", headers=owner, json={"decision": "accepted"}
    ).json()
    client.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        headers=owner,
        json={"client_message_id": str(uuid.uuid4()), "content": "공유하면 안 되는 사생활"},
    )
    assert (
        client.post(f"/api/v1/chat/sessions/{session['id']}/end", headers=owner).status_code == 200
    )
    assert db_session.get(SessionAnalysis, uuid.UUID(session["id"])) is not None
    insights = client.get("/api/v1/insights", headers=owner)
    assert insights.status_code == 200 and insights.json()["status"] == "collecting"
    invitation = client.post("/api/v1/caregivers/invitations", headers=owner).json()
    device = str(uuid.uuid4())
    client.post("/api/v1/users/bootstrap", json={"device_id": device, "display_name": "보호자"})
    caregiver = {"X-Device-ID": device}
    accepted = client.post(
        "/api/v1/caregivers/accept", headers=caregiver, json={"code": invitation["code"]}
    )
    assert accepted.status_code == 201
    link = accepted.json()["id"]
    report_url = f"/api/v1/caregivers/links/{link}/report"
    report = client.get(report_url, headers=caregiver)
    assert report.status_code == 200
    assert (
        "사생활" not in report.text
        and "messages" not in report.text
        and "content" not in report.text
    )
    assert (
        client.get(f"/api/v1/chat/sessions/{session['id']}", headers=caregiver).status_code == 404
    )
    assert (
        client.post(
            "/api/v1/caregivers/accept", headers=caregiver, json={"code": invitation["code"]}
        ).status_code
        == 404
    )
    consent(client, owner, share_mood=False, share_language=False)
    report = client.get(report_url, headers=caregiver).json()
    assert report["mood"] is None and report["language"] is None
    consent(client, owner, analysis_allowed=False, caregiver_share_allowed=False)
    assert client.get(report_url, headers=caregiver).status_code == 404
    assert db_session.get(SessionAnalysis, uuid.UUID(session["id"])) is None
    assert client.get("/api/v1/insights", headers=owner).status_code == 403
    consent(client, owner)
    retry = client.post(f"/api/v1/chat/sessions/{session['id']}/analysis", headers=owner)
    assert retry.status_code == 409  # Reconsenting never regenerates withdrawn historical analysis.
