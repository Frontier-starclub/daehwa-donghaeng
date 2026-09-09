import uuid

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.models import ChatMessage, ChatSession, DurCheck, MedicationScan
from app.providers import (
    HttpChatProvider,
    HttpDURProvider,
    HttpOCRProvider,
    get_chat_provider,
    get_dur_provider,
    get_ocr_provider,
)


@pytest.mark.parametrize("operation", ["ocr", "dur", "opening", "reply"])
@pytest.mark.parametrize("failure", ["timeout", "connection", 400, 503, "json", "missing"])
def test_502_persistence_and_retry(registered_client, db_session, operation, failure):
    client, headers = registered_client
    session_id = None
    if operation == "reply":
        started = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"decision": "accepted"}
        )
        session_id = started.json()["id"]
    if operation == "dur":
        saved = client.post(
            "/api/v1/medications/batch", headers=headers, json={"items": [{"name": "약"}]}
        )
        medication_id = saved.json()[0]["id"]

    calls = []
    should_fail = True

    def handler(request):
        calls.append(request)
        if should_fail:
            if failure == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            if failure == "connection":
                raise httpx.ConnectError("offline", request=request)
            if isinstance(failure, int):
                return httpx.Response(failure, text="private upstream body")
            return (
                httpx.Response(200, content=b"not-json")
                if failure == "json"
                else httpx.Response(200, json={})
            )
        return httpx.Response(
            200,
            json={
                "ocr": {"items": [{"name": "약"}]},
                "dur": {"warnings": []},
                "opening": {"content": "안녕하세요"},
                "reply": {"content": "반가워요"},
            }[operation],
        )

    provider_type, dependency = {
        "ocr": (HttpOCRProvider, get_ocr_provider),
        "dur": (HttpDURProvider, get_dur_provider),
        "opening": (HttpChatProvider, get_chat_provider),
        "reply": (HttpChatProvider, get_chat_provider),
    }[operation]
    provider = provider_type("http://ai:8100", 0.1, transport=httpx.MockTransport(handler))
    app.dependency_overrides[dependency] = lambda: provider
    message_id = str(uuid.uuid4())

    def invoke():
        if operation == "ocr":
            return client.post(
                "/api/v1/medication-scans",
                headers=headers,
                files={"image": ("label.jpg", b"image", "image/jpeg")},
            )
        if operation == "dur":
            return client.post(
                "/api/v1/dur-checks", headers=headers, json={"medication_ids": [medication_id]}
            )
        if operation == "opening":
            return client.post(
                "/api/v1/chat/sessions", headers=headers, json={"decision": "accepted"}
            )
        return client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": message_id, "content": "산책했어요"},
        )

    failed = invoke()
    assert failed.status_code == 502
    code = {"ocr": "OCR", "dur": "DUR", "opening": "CHAT", "reply": "CHAT"}[operation]
    assert failed.json()["code"] == f"{code}_PROVIDER_ERROR"
    assert set(failed.json()) == {"code", "message", "details"}
    assert "private upstream body" not in failed.text
    if operation in {"ocr", "dur"}:
        record = db_session.scalars(
            select(MedicationScan if operation == "ocr" else DurCheck)
        ).one()
        assert record.status == "failed" and record.provider == "remote"
        assert record.error_code == f"{code}_PROVIDER_ERROR"
    elif operation == "opening":
        assert db_session.scalars(select(ChatSession)).all() == []
        assert db_session.scalars(select(ChatMessage)).all() == []
        assert client.get("/api/v1/chat/sessions/current", headers=headers).json() is None
    else:
        current = client.get("/api/v1/chat/sessions/current", headers=headers).json()
        assert current["user_message_count"] == 0 and len(current["messages"]) == 1
        assert db_session.scalars(select(ChatMessage).where(ChatMessage.role == "user")).all() == []

    should_fail = False
    recovered = invoke()
    assert recovered.status_code == (201 if operation in {"opening", "dur"} else 200)
    if operation in {"reply", "opening"}:
        # Replay must be served from DB even when AI becomes unavailable again.
        should_fail = True
        assert invoke().json() == recovered.json()
        assert len(calls) == 2
        current = client.get("/api/v1/chat/sessions/current", headers=headers).json()
        assert current["user_message_count"] == (1 if operation == "reply" else 0)
        assert [m["sequence_no"] for m in current["messages"]] == (
            [1, 2, 3] if operation == "reply" else [1]
        )


def test_remote_empty_ocr_keeps_existing_422_contract(registered_client, db_session):
    client, headers = registered_client
    provider = HttpOCRProvider(
        "http://ai:8100",
        1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"items": []})),
    )
    app.dependency_overrides[get_ocr_provider] = lambda: provider
    response = client.post(
        "/api/v1/medication-scans",
        headers=headers,
        files={"image": ("label.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 422 and response.json()["code"] == "OCR_EMPTY"
    scan = db_session.scalars(select(MedicationScan)).one()
    assert scan.status == "empty" and scan.result_json == []
