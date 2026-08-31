"""Run the complete demo happy path against a running backend."""

import json
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
DEVICE_ID = str(uuid.uuid4())
HEADERS = {"X-Device-ID": DEVICE_ID}


def request(
    method: str,
    path: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict | list:
    body = None if payload is None else json.dumps(payload).encode()
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    req = Request(BASE_URL + path, data=body, headers=all_headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"{method} {path}: {exc.code} {exc.read().decode()}") from exc


def upload_mock_image() -> dict:
    boundary = "frontier-smoke-boundary"
    image = b"frontier-demo-image"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image"; filename="bag.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + image + f"\r\n--{boundary}--\r\n".encode()
    req = Request(
        BASE_URL + "/api/v1/medication-scans?scenario=success",
        data=body,
        headers={
            **HEADERS,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read())


def main() -> None:
    request(
        "POST",
        "/api/v1/users/bootstrap",
        {"device_id": DEVICE_ID, "display_name": "Smoke Test"},
    )
    scan = upload_mock_image()
    medications = request(
        "POST",
        "/api/v1/medications/batch",
        {"scan_id": scan["id"], "items": scan["items"]},
        HEADERS,
    )
    dur = request(
        "POST",
        "/api/v1/dur-checks?scenario=warning",
        {"medication_ids": [item["id"] for item in medications]},
        HEADERS,
    )
    request(
        "PUT",
        f"/api/v1/medications/{medications[0]['id']}/schedules",
        {"schedules": [{"time_slot": "morning", "remind_at": "08:00:00"}]},
        HEADERS,
    )
    events = request("GET", "/api/v1/medication-events/today", headers=HEADERS)
    request(
        "PUT",
        f"/api/v1/medication-events/{events[0]['id']}/response",
        {"status": "taken"},
        HEADERS,
    )
    session = request(
        "POST", "/api/v1/chat/sessions", {"decision": "accepted"}, HEADERS
    )
    request(
        "POST",
        f"/api/v1/chat/sessions/{session['id']}/messages",
        {"client_message_id": str(uuid.uuid4()), "content": "오늘 산책했어요."},
        HEADERS,
    )
    ended = request(
        "POST", f"/api/v1/chat/sessions/{session['id']}/end", headers=HEADERS
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "medications": len(medications),
                "dur_status": dur["status"],
                "events": len(events),
                "chat_status": ended["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
