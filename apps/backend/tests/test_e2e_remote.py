"""Actual Backend → AI SDK HTTP boundary fixture, with a migrated database."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from scripts.smoke_test import run_smoke
from tests.server_helpers import process_env, serve_app
from tests.test_remote_integration import (
    BACKEND_ROOT,
    DEFAULT_AI_SOURCE,
    integration_database,  # noqa: F401 -- shared pytest fixture
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("llm_provider", ["anthropic", "gemini"])
def test_complete_remote_flow(integration_database, llm_provider):  # noqa: F811 -- pytest fixture
    engine, env = integration_database
    with serve_app(
        DEFAULT_AI_SOURCE,
        process_env(E2E_EXTERNAL_FIXTURES="1", LLM_PROVIDER=llm_provider),
        entrypoint="tests.e2e_fixture_server:app",
    ) as (ai_url, _):
        env.update(PROVIDER_MODE="remote", AI_SERVICE_URL=ai_url, AI_SERVICE_TIMEOUT="10")
        with (
            serve_app(BACKEND_ROOT, env) as (url, _),
            httpx.Client(base_url=url, timeout=20, trust_env=False) as client,
        ):
            run_complete_flow(client, concurrent=engine.dialect.name == "postgresql")


def run_complete_flow(client, *, concurrent=False):
    result = run_smoke(client, expected_provider="remote")
    owner = {"X-Device-ID": result["device_id"]}
    dur = client.get(f"/api/v1/dur-checks/{result['dur_id']}", headers=owner).json()
    assert {w["warning_type"] for w in dur["warnings"]} == {
        "usjnt_taboo",
        "elderly",
        "efficacy_duplicate",
    }
    consent = {
        "analysis_allowed": True,
        "caregiver_share_allowed": True,
        "share_medication": True,
        "share_mood": True,
        "share_language": False,
    }
    assert client.put("/api/v1/users/me/consents", headers=owner, json=consent).status_code == 200
    session = client.post(
        "/api/v1/chat/sessions", headers=owner, json={"decision": "accepted"}
    ).json()
    path = f"/api/v1/chat/sessions/{session['id']}"
    for content in ("오늘 산책했어요", "이전 이야기를 기억하세요?"):
        reply = client.post(
            path + "/messages",
            headers=owner,
            json={"client_message_id": str(uuid.uuid4()), "content": content},
        )
        assert reply.status_code == 200, reply.text
    assert "앞서 산책" in reply.json()["assistant_message"]["content"]
    assert client.post(path + "/end", headers=owner).status_code == 200
    insights = client.get("/api/v1/insights", headers=owner).json()
    assert insights["current"]["mood_score"] == 0.4
    assert insights["partial_sessions"] == 0 and insights["has_demo_data"] is False
    assert insights["status"] == "collecting" and insights["change"] == {}

    # Simultaneous batch retries must register one item, including with PostgreSQL locks.
    batch = {"request_id": str(uuid.uuid4()), "items": [{"name": "동시등록테스트약"}]}
    with ThreadPoolExecutor(max_workers=2 if concurrent else 1) as pool:
        responses = list(
            pool.map(
                lambda _: client.post("/api/v1/medications/batch", headers=owner, json=batch),
                range(2),
            )
        )
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    med = result["medication_ids"][0]
    schedules = f"/api/v1/medications/{med}/schedules"
    assert client.put(schedules, headers=owner, json={"schedules": []}).status_code == 200
    assert (
        client.get("/api/v1/medication-events/today", headers=owner).json()[0]["status"] == "taken"
    )

    invite = client.post("/api/v1/caregivers/invitations", headers=owner).json()
    caregiver = {"X-Device-ID": str(uuid.uuid4())}
    client.post(
        "/api/v1/users/bootstrap",
        json={"device_id": caregiver["X-Device-ID"], "display_name": "E2E 보호자"},
    )
    accepted = client.post(
        "/api/v1/caregivers/accept", headers=caregiver, json={"code": invite["code"]}
    )
    assert accepted.status_code == 201, accepted.text
    report_path = f"/api/v1/caregivers/links/{accepted.json()['id']}/report"
    report = client.get(report_path, headers=caregiver)
    assert report.status_code == 200
    assert report.json()["mood"]["current"]["mood_score"] == 0.4
    assert report.json()["language"] is None
    assert report.json()["medication"]["taken"] == 1
    assert "산책" not in report.text and "messages" not in report.text
    assert client.get(path, headers=caregiver).status_code == 404
    consent.update(analysis_allowed=False, caregiver_share_allowed=False)
    assert client.put("/api/v1/users/me/consents", headers=owner, json=consent).status_code == 200
    assert client.get(report_path, headers=caregiver).status_code == 404
    assert client.get("/api/v1/insights", headers=owner).status_code == 403
    return result
