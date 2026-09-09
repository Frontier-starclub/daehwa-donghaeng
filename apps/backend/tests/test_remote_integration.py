import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatSession,
    DurCheck,
    Medication,
    MedicationEvent,
    MedicationScan,
)
from scripts.smoke_test import PNG_1X1, run_smoke
from tests.server_helpers import process_env, serve_app, stop_process

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AI_SOURCE = BACKEND_ROOT.parents[2] / "daehwa-donghaeng-frontend/client-repo/ai"
pytestmark = pytest.mark.integration


@pytest.fixture
def integration_database(tmp_path):
    # PostgreSQL uses an isolated schema, never drops existing application tables.
    url = os.getenv("INTEGRATION_DATABASE_URL")
    admin_engine = None
    if url:
        admin_engine = create_engine(url)
        assert admin_engine.dialect.name == "postgresql", "Use PostgreSQL or leave URL unset"
        schema = "integration_" + uuid.uuid4().hex
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        env = process_env(DATABASE_URL=url, PGOPTIONS=f"-csearch_path={schema}")
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        url = f"sqlite+pysqlite:///{tmp_path / 'integration.db'}"
        env = process_env(DATABASE_URL=url)
        env.pop("PGOPTIONS", None)
        engine = create_engine(url)
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
        yield engine, env
    finally:
        engine.dispose()
        if admin_engine is not None:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()


@pytest.fixture
def ai_server():
    source = Path(os.getenv("AI_SOURCE_DIR", str(DEFAULT_AI_SOURCE))).resolve()
    assert (source / "app/main.py").is_file(), (
        "AI source missing. Set AI_SOURCE_DIR to client-repo/ai, or use -m 'not integration'."
    )
    with serve_app(source, process_env(PROVIDER_MODE="mock", APP_ENV="development")) as server:
        with httpx.Client(base_url=server[0], trust_env=False) as client:
            assert client.get("/health/live").json()["provider_mode"] == "mock"
        yield server


def test_real_http_flow_and_ai_shutdown(ai_server, integration_database):
    ai_url, ai_process = ai_server
    engine, env = integration_database
    env.update(PROVIDER_MODE="remote", AI_SERVICE_URL=ai_url, AI_SERVICE_TIMEOUT="1")
    with (
        serve_app(BACKEND_ROOT, env) as (url, _),
        httpx.Client(base_url=url, timeout=10, trust_env=False) as client,
    ):
        result = run_smoke(client, expected_provider="remote")
        user_id = uuid.UUID(result["user_id"])
        with Session(engine) as db:
            medications = db.scalars(select(Medication).where(Medication.user_id == user_id)).all()
            assert len(medications) == result["medications"] == 2
            scan = db.get(MedicationScan, uuid.UUID(result["scan_id"]))
            assert scan.provider == "remote" and scan.status == "success" and scan.result_json
            dur = db.get(DurCheck, uuid.UUID(result["dur_id"]))
            assert dur.provider == "remote" and dur.status == "warnings" and len(dur.warnings) == 1
            assert set(dur.warnings[0].medication_ids) == set(result["medication_ids"])
            event = db.scalars(
                select(MedicationEvent).where(MedicationEvent.user_id == user_id)
            ).one()
            assert event.status == "taken" and event.responded_at
            chat = db.get(ChatSession, uuid.UUID(result["chat_session_id"]))
            assert chat.status == "ended" and chat.user_message_count == 1
            assert [m.role for m in chat.messages] == ["assistant", "user", "assistant"]

        headers = {"X-Device-ID": result["device_id"]}

        def start_session():
            response = client.post(
                "/api/v1/chat/sessions", headers=headers, json={"decision": "accepted"}
            )
            assert response.status_code == 201, response.text
            return response.json()

        if engine.dialect.name == "postgresql":
            creation_barrier = Barrier(2)

            def concurrent_start(_):
                creation_barrier.wait(timeout=5)
                return start_session()

            with ThreadPoolExecutor(max_workers=2) as pool:
                sessions = list(pool.map(concurrent_start, range(2)))
            assert sessions[0]["id"] == sessions[1]["id"]
            assert len(sessions[0]["messages"]) == len(sessions[1]["messages"]) == 1
            active_id = sessions[0]["id"]
        else:
            active_id = start_session()["id"]
        # With real PG locks, simultaneous retries return the same stored turn.
        if engine.dialect.name == "postgresql":
            payload = {"client_message_id": str(uuid.uuid4()), "content": "동시 재전송"}
            message_barrier = Barrier(2)

            def send():
                message_barrier.wait(timeout=5)
                response = client.post(
                    f"/api/v1/chat/sessions/{active_id}/messages", headers=headers, json=payload
                )
                assert response.status_code == 200, response.text
                return response.json()

            with ThreadPoolExecutor(max_workers=2) as pool:
                turns = list(pool.map(lambda _: send(), range(2)))
            assert turns[0] == turns[1]

        before = client.get("/api/v1/chat/sessions/current", headers=headers).json()
        assert before["user_message_count"] == (1 if engine.dialect.name == "postgresql" else 0)
        stop_process(ai_process)
        requests = [
            (
                "/api/v1/medication-scans",
                "OCR_PROVIDER_ERROR",
                {"files": {"image": ("label.png", PNG_1X1, "image/png")}},
            ),
            ("/api/v1/dur-checks", "DUR_PROVIDER_ERROR", {"json": {}}),
            (
                f"/api/v1/chat/sessions/{active_id}/messages",
                "CHAT_PROVIDER_ERROR",
                {"json": {"client_message_id": str(uuid.uuid4()), "content": "재시도 예정"}},
            ),
        ]
        for path, code, kwargs in requests:
            response = client.post(path, headers=headers, **kwargs)
            assert response.status_code == 502 and response.json()["code"] == code
        after = client.get("/api/v1/chat/sessions/current", headers=headers).json()
        assert after == before
        with Session(engine) as db:
            failures = db.scalars(
                select(DurCheck).where(DurCheck.user_id == user_id, DurCheck.status == "failed")
            ).all()
            assert len(failures) == 1 and failures[0].error_code == "DUR_PROVIDER_ERROR"
            messages = db.scalars(
                select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(active_id))
            ).all()
            assert len(messages) == len(before["messages"])


def test_real_http_mock_mode(integration_database):
    _, env = integration_database
    # An unreachable AI address proves internal mock never calls HTTP.
    env.update(PROVIDER_MODE="mock", AI_SERVICE_URL="http://127.0.0.1:1")
    with (
        serve_app(BACKEND_ROOT, env) as (url, _),
        httpx.Client(base_url=url, timeout=10, trust_env=False) as client,
    ):
        assert run_smoke(client, expected_provider="mock")["status"] == "ok"


def test_real_ai_read_timeouts(ai_server, integration_database):
    from tests.server_helpers import delay_proxy

    _, env = integration_database
    with delay_proxy(ai_server[0]) as (proxy_url, proxy):
        env.update(PROVIDER_MODE="remote", AI_SERVICE_URL=proxy_url, AI_SERVICE_TIMEOUT="0.5")
        with (
            serve_app(BACKEND_ROOT, env) as (url, _),
            httpx.Client(base_url=url, timeout=5, trust_env=False) as client,
        ):
            result = run_smoke(client, expected_provider="remote")
            headers = {"X-Device-ID": result["device_id"]}
            started = client.post(
                "/api/v1/chat/sessions", headers=headers, json={"decision": "accepted"}
            )
            assert started.status_code == 201
            active_id = started.json()["id"]
            opening_headers = {"X-Device-ID": str(uuid.uuid4())}
            client.post(
                "/api/v1/users/bootstrap",
                json={"device_id": opening_headers["X-Device-ID"], "display_name": "Timeout test"},
            )
            proxy.delay = 1.0
            for path, request_headers, code, kwargs in [
                (
                    "/api/v1/medication-scans",
                    headers,
                    "OCR_PROVIDER_ERROR",
                    {"files": {"image": ("label.png", PNG_1X1, "image/png")}},
                ),
                ("/api/v1/dur-checks", headers, "DUR_PROVIDER_ERROR", {"json": {}}),
                (
                    "/api/v1/chat/sessions",
                    opening_headers,
                    "CHAT_PROVIDER_ERROR",
                    {"json": {"decision": "accepted"}},
                ),
                (
                    f"/api/v1/chat/sessions/{active_id}/messages",
                    headers,
                    "CHAT_PROVIDER_ERROR",
                    {"json": {"client_message_id": str(uuid.uuid4()), "content": "안녕하세요"}},
                ),
            ]:
                response = client.post(path, headers=request_headers, **kwargs)
                assert response.status_code == 502 and response.json()["code"] == code
            current = client.get("/api/v1/chat/sessions/current", headers=headers).json()
            assert current["user_message_count"] == 0 and len(current["messages"]) == 1
            assert (
                client.get("/api/v1/chat/sessions/current", headers=opening_headers).json() is None
            )
