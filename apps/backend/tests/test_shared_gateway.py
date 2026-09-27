import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.shared_gateway import MAX_BODY, create_app

ACCESS = "test-api-access-" + "a" * 32


@pytest.fixture
def gateway():
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(201, json={"ok": True})

    app = create_app(
        {"access_token": ACCESS}, transport=httpx.MockTransport(upstream),
    )
    with TestClient(app) as client:
        yield client, calls


def test_rejects_anonymous_and_incorrect_token_before_upstream(gateway):
    client, calls = gateway
    for token in ("", "incorrect"):
        response = client.post(
            "/api/v1/users/bootstrap", headers={"Authorization": f"Bearer {token}"},
            json={"device_id": "test-device", "display_name": "Tester"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "TEST_ACCESS_DENIED"
    assert not calls
    assert client.get("/docs").status_code == 404
    assert client.get("/health/live").status_code == 200


def test_preserves_json_query_device_but_never_forwards_gate_or_cookies(gateway):
    client, calls = gateway
    response = client.post(
        "/api/v1/users/bootstrap?scenario=success", json={"display_name": "테스트"},
        headers={
            "Authorization": f"Bearer {ACCESS}", "X-Device-ID": "test-device",
            "Cookie": "private=value", "X-Forwarded-Host": "attacker.invalid",
        },
    )
    assert response.status_code == 201
    request = calls[0]
    assert str(request.url) == "http://127.0.0.1:8090/api/v1/users/bootstrap?scenario=success"
    assert request.headers["X-Device-ID"] == "test-device"
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert "x-forwarded-host" not in request.headers
    assert "테스트" in request.content.decode()


def test_multipart_and_body_limit(gateway):
    client, calls = gateway
    headers = {"Authorization": f"Bearer {ACCESS}", "X-Device-ID": "test-device"}
    response = client.post(
        "/api/v1/medication-scans", headers=headers,
        files={"image": ("label.png", b"image-bytes", "image/png")},
    )
    assert response.status_code == 201
    assert b"image-bytes" in calls[0].content
    assert "multipart/form-data" in calls[0].headers["content-type"]
    assert client.post(
        "/api/v1/medication-scans", headers=headers, content=b"x" * (MAX_BODY + 1)
    ).status_code == 413
    assert len(calls) == 1


def test_server_never_distributes_apk(gateway):
    client, calls = gateway
    assert client.get("/install/wrong").status_code == 404
    assert client.get(f"/install/{ACCESS}/app.apk").status_code == 404
    assert client.get("/daehwa-donghaeng-test.apk").status_code == 404
    assert not calls


def test_upstream_down_returns_retryable_error():
    def offline(request):
        raise httpx.ConnectError("offline")

    app = create_app(
        {"access_token": ACCESS},
        transport=httpx.MockTransport(offline),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {ACCESS}"}
        )
    assert response.status_code == 503
    assert response.json()["code"] == "SERVER_UNAVAILABLE"


def test_gateway_fails_closed_without_strong_token():
    for config in ({}, {"access_token": "short"}):
        with pytest.raises(ValueError):
            create_app(config)
