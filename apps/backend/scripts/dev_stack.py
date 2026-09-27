"""Start PostgreSQL, AI and Backend locally. Keys are read only by the AI process.

Run from anywhere with the backend virtualenv Python. --fixture uses explicit
synthetic external responses and a separate database, never real user data.
"""

import argparse
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[1]
AI = ROOT.parent / "daehwa-donghaeng-frontend/client-repo/ai"
API_KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DATA_GO_KR_SERVICE_KEY")


def ai_environment(config, *, fixture=False, llm_provider=None):
    """Select one LLM; never require or forward the other provider's key."""
    provider = llm_provider or config.get("LLM_PROVIDER") or "anthropic"
    if provider not in ("anthropic", "gemini"):
        raise SystemExit("LLM_PROVIDER는 anthropic 또는 gemini여야 합니다.")
    llm_key = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    required = (llm_key, "DATA_GO_KR_SERVICE_KEY")
    missing = [key for key in required if not (config.get(key) or "").strip()]
    if missing and not fixture:
        raise SystemExit(".env에 입력할 키: " + ", ".join(missing))
    return {
        "APP_ENV": "development",
        "PROVIDER_MODE": "remote",
        "LLM_PROVIDER": provider,
        **{key: "e2e-fixture" if fixture else config[key].strip() for key in required},
        "OCR_MODEL": config.get("OCR_MODEL") or "claude-opus-5",
        "CHAT_MODEL": config.get("CHAT_MODEL") or "claude-opus-5",
        "GEMINI_OCR_MODEL": config.get("GEMINI_OCR_MODEL") or "gemini-3.8-flash",
        "GEMINI_CHAT_MODEL": config.get("GEMINI_CHAT_MODEL") or "gemini-3.8-flash",
    }


def clean_environment(env):
    clean = dict(env)
    for key in (*API_KEYS, "DATABASE_URL", "PGOPTIONS", "PYTHONPATH"):
        clean.pop(key, None)
    return clean


def available(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--llm-provider", choices=("anthropic", "gemini"))
    parser.add_argument("--check", action="store_true", help="Preflight only; never prints secrets")
    parser.add_argument("--backend-port", type=int, default=8090)
    parser.add_argument("--ai-port", type=int, default=8100)
    parser.add_argument("--db-port", type=int, default=15432)
    args = parser.parse_args()
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    selected_ai = ai_environment(config, fixture=args.fixture, llm_provider=args.llm_provider)
    toolbox = ROOT / ".local/tools/postgres"
    pg = toolbox / "usr/lib/postgresql/16/bin"
    python_ai = AI / ".venv/bin/python"
    for path in (pg / "pg_ctl", python_ai, BACKEND / "alembic.ini"):
        if not path.exists():
            raise SystemExit(f"준비되지 않은 도구: {path}. scripts/setup_local.sh를 실행해주세요.")
    for port in (args.backend_port, args.ai_port, args.db_port):
        try:
            available(port)
        except OSError:
            raise SystemExit(f"포트 {port}를 다른 프로세스가 사용 중입니다.") from None
    if args.check:
        print(f"LLM: {selected_ai['LLM_PROVIDER']}. 실행 도구·환경변수·포트 확인 완료.")
        print("외부 키의 유효성은 실제 요청으로 확인합니다.")
        return
    state = ROOT / ".local" / ("fixture" if args.fixture else "development")
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    clean = clean_environment(os.environ)
    pg_env = {**clean, "LD_LIBRARY_PATH": str(toolbox / "usr/lib/x86_64-linux-gnu")}
    data = state / "postgres-data"
    password_file = state / "postgres-password"
    if not password_file.exists():
        password_file.write_text(secrets.token_urlsafe(32))
        password_file.chmod(0o600)
    password = password_file.read_text().strip()
    if not (data / "PG_VERSION").exists():
        subprocess.run(
            [
                str(pg / "initdb"),
                "-D",
                str(data),
                "-L",
                str(toolbox / "usr/share/postgresql/16"),
                "-U",
                "frontier",
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
                "--pwfile",
                str(password_file),
            ],
            env=pg_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    processes = []
    logs = []
    database_started = False

    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        subprocess.run(
            [
                str(pg / "pg_ctl"),
                "-D",
                str(data),
                "-l",
                str(state / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {args.db_port} -k {state}",
                "start",
            ],
            env=pg_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        database_started = True
        backend_env = {
            **clean,
            "APP_ENV": "development",
            "PROVIDER_MODE": "remote",
            "DATABASE_URL": f"postgresql+psycopg://frontier:{password}@127.0.0.1:{args.db_port}/postgres",
            "AI_SERVICE_URL": f"http://127.0.0.1:{args.ai_port}",
            "AI_SERVICE_TIMEOUT": "45",
        }
        ai_env = {
            **clean,
            **selected_ai,
        }
        if args.fixture:
            ai_env.update(E2E_EXTERNAL_FIXTURES="1")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=backend_env,
            check=True,
        )
        for directory, executable, env, port, entry in (
            (
                AI,
                python_ai,
                ai_env,
                args.ai_port,
                "tests.e2e_fixture_server:app" if args.fixture else "app.main:app",
            ),
            (BACKEND, sys.executable, backend_env, args.backend_port, "app.main:app"),
        ):
            log = (state / f"{directory.name}.log").open("a")
            logs.append(log)
            process = subprocess.Popen(
                [
                    str(executable),
                    "-m",
                    "uvicorn",
                    entry,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(process)
            with httpx.Client(timeout=1, trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f"{directory.name} 시작 실패. {log.name} 확인")
                    try:
                        if client.get(f"http://127.0.0.1:{port}/health/live").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError(f"{directory.name} 시작 시간 초과")
        print(
            "외부 응답은 가상 테스트 데이터입니다."
            if args.fixture
            else f"실제 외부 API 연결 모드입니다. LLM: {selected_ai['LLM_PROVIDER']}",
            flush=True,
        )
        print(f"API: http://localhost:{args.backend_port}/api/v1 · 종료: Ctrl+C", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        raise RuntimeError("서버가 종료됐습니다. .local 아래 로그를 확인해주세요.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        if database_started:
            subprocess.run(
                [str(pg / "pg_ctl"), "-D", str(data), "stop", "-m", "fast"],
                env=pg_env,
                stdout=subprocess.DEVNULL,
                check=False,
            )


if __name__ == "__main__":
    main()
