"""Real loopback HTTP servers with bounded startup and unconditional cleanup."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

import httpx


def process_env(**overrides):
    env = {**os.environ, **overrides}
    # Both repositories use the package name 'app'; isolate subprocess imports.
    env.pop("PYTHONPATH", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("DATA_GO_KR_SERVICE_KEY", None)
    return env


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def serve_app(directory, env):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryFile(mode="w+") as logs:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=directory,
            env=env,
            stdout=logs,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            ready = False
            with httpx.Client(base_url=url, timeout=0.5, trust_env=False) as client:
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        if client.get("/health/live").status_code == 200:
                            ready = True
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.05)
            if not ready:
                logs.seek(0)
                raise RuntimeError(f"HTTP server failed to start: {logs.read()}")
            yield url, process
        finally:
            stop_process(process)


@contextmanager
def delay_proxy(upstream_url):
    """Forward to the real AI mock, optionally delaying replies past its timeout."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            with httpx.Client(base_url=upstream_url, timeout=5, trust_env=False) as client:
                response = client.post(
                    self.path,
                    content=body,
                    headers={"Content-Type": self.headers["Content-Type"]},
                )
            time.sleep(server.delay)
            try:
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected: backend disconnected on its read timeout.

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.delay = 0
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
