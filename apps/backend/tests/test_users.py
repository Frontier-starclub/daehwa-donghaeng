from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_bootstrap_is_idempotent(client: TestClient) -> None:
    payload = {
        "device_id": "22222222-2222-4222-8222-222222222222",
        "display_name": "첫 이름",
    }
    first = client.post("/api/v1/users/bootstrap", json=payload)
    payload["display_name"] = "바뀐 이름"
    second = client.post("/api/v1/users/bootstrap", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["display_name"] == "바뀐 이름"
    assert second.json()["consent"]["analysis_allowed"] is False


def test_consent_is_separate(registered_client) -> None:
    client, headers = registered_client
    response = client.put(
        "/api/v1/users/me/consents",
        headers=headers,
        json={"analysis_allowed": True, "caregiver_share_allowed": False},
    )
    assert response.status_code == 200
    assert response.json()["consent"] == {
        "analysis_allowed": True,
        "caregiver_share_allowed": False,
        "updated_at": response.json()["consent"]["updated_at"],
    }


def test_unregistered_device_is_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/users/me",
        headers={"X-Device-ID": "33333333-3333-4333-8333-333333333333"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "DEVICE_NOT_REGISTERED"

