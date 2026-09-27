"""Run a disposable E2E stack, optionally executing a command inside its lifetime.

python -m tests.serve_e2e --ready-file /tmp/daehwa-e2e.json
INTEGRATION_DATABASE_URL selects an isolated PostgreSQL schema; otherwise SQLite.
Only external HTTP boundaries use synthetic responses; no real API keys are read.
"""

import argparse
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from tests.server_helpers import process_env, serve_app
from tests.test_remote_integration import BACKEND_ROOT, DEFAULT_AI_SOURCE, integration_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--llm-provider", choices=("anthropic", "gemini"), default="anthropic")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="daehwa-e2e-") as directory:
        fixture = integration_database.__wrapped__(Path(directory))
        _, env = next(fixture)
        try:
            with serve_app(
                DEFAULT_AI_SOURCE,
                process_env(E2E_EXTERNAL_FIXTURES="1", LLM_PROVIDER=args.llm_provider),
                entrypoint="tests.e2e_fixture_server:app",
            ) as (ai_url, _):
                env.update(PROVIDER_MODE="remote", AI_SERVICE_URL=ai_url, AI_SERVICE_TIMEOUT="45")
                with serve_app(BACKEND_ROOT, env) as (url, _):
                    info = {"api_url": url + "/api/v1", "backend_url": url, "ai_url": ai_url}
                    if args.ready_file:
                        args.ready_file.write_text(json.dumps(info))
                    print(json.dumps(info), flush=True)
                    if args.command:
                        command = args.command[1:] if args.command[0] == "--" else args.command
                        command = [item.replace("{api_url}", info["api_url"]) for item in command]
                        result = subprocess.run(
                            command, env={**os.environ, "TEST_API_BASE_URL": info["api_url"]}
                        )
                        if result.returncode:
                            raise SystemExit(result.returncode)
                    else:
                        threading.Event().wait()
        finally:
            fixture.close()
            if args.ready_file:
                args.ready_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
