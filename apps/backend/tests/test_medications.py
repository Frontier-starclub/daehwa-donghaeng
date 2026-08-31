from fastapi.testclient import TestClient


def create_medications(client: TestClient, headers: dict[str, str]) -> list[dict]:
    scan = client.post(
        "/api/v1/medication-scans?scenario=success",
        headers=headers,
        files={"image": ("bag.jpg", b"fake-image", "image/jpeg")},
    )
    assert scan.status_code == 200
    result = scan.json()
    confirmed = client.post(
        "/api/v1/medications/batch",
        headers=headers,
        json={"scan_id": result["id"], "items": result["items"]},
    )
    assert confirmed.status_code == 201
    return confirmed.json()


def test_ocr_medication_and_dur_flow(registered_client) -> None:
    client, headers = registered_client
    medications = create_medications(client, headers)
    assert len(medications) == 2
    assert all(item["source"] == "ocr" for item in medications)

    dur = client.post(
        "/api/v1/dur-checks?scenario=warning",
        headers=headers,
        json={"medication_ids": [item["id"] for item in medications]},
    )
    assert dur.status_code == 201
    assert dur.json()["status"] == "warnings"
    assert dur.json()["warnings"][0]["warning_type"] == "demo_warning"
    assert "의사·약사" in dur.json()["disclaimer"]


def test_ocr_failure_does_not_store_image(registered_client, db_session) -> None:
    client, headers = registered_client
    response = client.post(
        "/api/v1/medication-scans?scenario=failure",
        headers=headers,
        files={"image": ("bag.png", b"private-image-bytes", "image/png")},
    )
    assert response.status_code == 502
    assert response.json()["code"] == "OCR_PROVIDER_ERROR"

    from app.models import MedicationScan

    scan = db_session.query(MedicationScan).one()
    assert scan.status == "failed"
    assert "private-image-bytes" not in str(scan.result_json)


def test_schedule_and_response(registered_client) -> None:
    client, headers = registered_client
    medication = create_medications(client, headers)[0]
    schedule = client.put(
        f"/api/v1/medications/{medication['id']}/schedules",
        headers=headers,
        json={"schedules": [{"time_slot": "morning", "remind_at": "08:00:00"}]},
    )
    assert schedule.status_code == 200

    events = client.get("/api/v1/medication-events/today", headers=headers)
    assert events.status_code == 200
    assert len(events.json()) == 1

    event_id = events.json()[0]["id"]
    answered = client.put(
        f"/api/v1/medication-events/{event_id}/response",
        headers=headers,
        json={"status": "taken"},
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "taken"

