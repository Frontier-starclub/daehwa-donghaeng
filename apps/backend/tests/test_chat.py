import uuid


def test_chat_lifecycle_and_idempotency(registered_client) -> None:
    client, headers = registered_client
    started = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"decision": "accepted"},
    )
    assert started.status_code == 201
    session_id = started.json()["id"]
    assert started.json()["status"] == "active"
    assert started.json()["messages"][0]["role"] == "assistant"

    message_id = str(uuid.uuid4())
    payload = {"client_message_id": message_id, "content": "오늘 산책했어요."}
    first = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=headers,
        json=payload,
    )
    duplicate = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json()

    current = client.get("/api/v1/chat/sessions/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["user_message_count"] == 1
    assert len(current.json()["messages"]) == 3

    ended = client.post(
        f"/api/v1/chat/sessions/{session_id}/end", headers=headers
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"

    rejected = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid.uuid4()), "content": "더 말할게요."},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "CHAT_SESSION_CLOSED"


def test_decline_is_recorded(registered_client) -> None:
    client, headers = registered_client
    response = client.post(
        "/api/v1/chat/sessions",
        headers=headers,
        json={"decision": "declined"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "declined"
    assert response.json()["messages"] == []

