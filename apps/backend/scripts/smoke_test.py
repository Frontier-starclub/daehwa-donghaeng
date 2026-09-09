"""Run the full API flow in either provider mode against a running backend."""

import argparse
import base64
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4"
    "z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
)


def run_smoke(client, *, expected_provider: str | None = None, image: bytes = PNG_1X1):
    """Also used by integration tests; each run owns a fresh device/user."""
    device_id = str(uuid.uuid4())
    headers = {"X-Device-ID": device_id}

    def request(method, path, status=200, **kwargs):
        response = client.request(method, path, headers=headers, **kwargs)
        if response.status_code != status:
            raise RuntimeError(f"{method} {path}: {response.status_code} {response.text}")
        return response.json()

    user = request(
        "POST",
        "/api/v1/users/bootstrap",
        json={"device_id": device_id, "display_name": "Smoke Test"},
    )
    is_png = image.startswith(b"\x89PNG\r\n\x1a\n")
    scan = request(
        "POST",
        "/api/v1/medication-scans?scenario=success",
        files={
            "image": (
                "label.png" if is_png else "label.jpg",
                image,
                "image/png" if is_png else "image/jpeg",
            )
        },
    )
    assert scan["status"] == "success" and scan["items"]
    medications = request(
        "POST",
        "/api/v1/medications/batch",
        status=201,
        json={"scan_id": scan["id"], "items": scan["items"]},
    )
    listed = request("GET", "/api/v1/medications")
    assert {item["id"] for item in listed} == {item["id"] for item in medications}
    assert all(item["source"] == "ocr" for item in listed)
    dur = request(
        "POST",
        "/api/v1/dur-checks?scenario=warning",
        status=201,
        json={"medication_ids": [item["id"] for item in medications]},
    )
    assert dur["status"] in {"warnings", "no_warnings"}
    assert dur["disclaimer"]
    persisted_dur = request("GET", f"/api/v1/dur-checks/{dur['id']}")
    for key in ("id", "status", "provider", "warnings", "disclaimer"):
        assert persisted_dur[key] == dur[key]
    # SQLite omits timezone metadata; PostgreSQL may return the DB's timezone.
    def timestamp(value):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    assert timestamp(persisted_dur["checked_at"]) == timestamp(dur["checked_at"])
    if expected_provider:
        assert scan["provider"] == dur["provider"] == expected_provider
    schedules = request(
        "PUT",
        f"/api/v1/medications/{medications[0]['id']}/schedules",
        json={"schedules": [{"time_slot": "morning", "remind_at": "08:00:00"}]},
    )
    events = request("GET", "/api/v1/medication-events/today")
    assert len(events) == 1 and events[0]["schedule_id"] == schedules[0]["id"]
    answered = request(
        "PUT",
        f"/api/v1/medication-events/{events[0]['id']}/response",
        json={"status": "taken"},
    )
    assert answered["status"] == "taken" and answered["responded_at"]
    assert request("GET", "/api/v1/medication-events/today")[0]["status"] == "taken"
    session = request("POST", "/api/v1/chat/sessions", status=201, json={"decision": "accepted"})
    assert session["messages"][0]["content"] and session["user_message_count"] == 0
    payload = {"client_message_id": str(uuid.uuid4()), "content": "오늘 산책했어요."}
    path = f"/api/v1/chat/sessions/{session['id']}/messages"
    turn = request("POST", path, json=payload)
    assert turn["assistant_message"]["content"]
    assert request("POST", path, json=payload) == turn
    current = request("GET", "/api/v1/chat/sessions/current")
    assert current["id"] == session["id"]
    assert current["user_message_count"] == 1 and len(current["messages"]) == 3
    ended = request("POST", f"/api/v1/chat/sessions/{session['id']}/end")
    assert ended["status"] == "ended"
    return {
        "status": "ok",
        "provider": scan["provider"],
        "device_id": device_id,
        "user_id": user["id"],
        "scan_id": scan["id"],
        "medication_ids": [item["id"] for item in medications],
        "medications": len(medications),
        "dur_id": dur["id"],
        "dur_status": dur["status"],
        "events": len(events),
        "chat_session_id": session["id"],
        "chat_status": ended["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default="http://localhost:8090")
    parser.add_argument("--expected-provider", choices=["mock", "remote"])
    parser.add_argument("--image", type=Path, help="Use a real JPEG/PNG after AI implementation")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=60, trust_env=False) as client:
        result = run_smoke(
            client,
            expected_provider=args.expected_provider,
            image=args.image.read_bytes() if args.image else PNG_1X1,
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
