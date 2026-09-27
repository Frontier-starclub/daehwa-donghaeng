"""Team test gateway. Only this loopback service is published through HTTPS.

The shared access token is a revocable team gate, not individual authentication.
Vendor API keys remain exclusively in the AI service. Configuration and APKs
live in the git-ignored .local/shared-server directory.
"""

import argparse
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / ".local/shared-server"
CONFIG = STATE / "config.json"
MAX_BODY = 11 * 1024 * 1024


def matches(candidate: str, expected: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def private_json(path: Path, content: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(content, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    path.chmod(0o600)


def prepare(base_url: str) -> None:
    url = urlsplit(base_url)
    if (
        url.scheme != "https" or not url.hostname or url.username or url.password
        or url.query or url.fragment or url.path not in ("", "/")
    ):
        raise SystemExit("공용 서버의 HTTPS 기본 주소를 입력해주세요. 경로·인증정보는 제외합니다.")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {
        "access_token": secrets.token_urlsafe(32),
        "download_token": secrets.token_urlsafe(32),
    }
    config["base_url"] = base_url.rstrip("/")
    private_json(CONFIG, config)
    private_json(STATE / "android-defines.json", {
        "API_BASE_URL": config["base_url"] + "/api/v1",
        "TEST_ACCESS_TOKEN": config["access_token"],
    })
    print("공용 서버 설정과 Android 빌드 설정을 .local/shared-server에 저장했습니다.")


def create_app(config: dict, *, transport=None, apk_path: Path | None = None) -> FastAPI:
    access = config.get("access_token", "")
    download = config.get("download_token", "")
    if len(access) < 32 or len(download) < 32 or access == download:
        raise ValueError("서로 다른 충분히 긴 API/다운로드 접근 키가 필요합니다.")
    apk_path = apk_path or STATE / "daehwa-donghaeng-test.apk"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8090", timeout=65, trust_env=False,
            follow_redirects=False, transport=transport,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        ) as client:
            app.state.backend = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/health/live")
    async def health():
        return {"status": "ok"}

    @app.get("/install/{code}", response_class=HTMLResponse)
    async def install(code: str):
        if not matches(code, download):
            return Response(status_code=404)
        ready = apk_path.is_file()
        action = (
            '<a href="' + code + '/app.apk">Android 앱 다운로드</a>'
            if ready else "<p>설치 파일을 준비하고 있습니다.</p>"
        )
        return HTMLResponse(
            '<!doctype html><html lang="ko"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>대화동행 설치</title><style>'
            'body{font:18px/1.7 sans-serif;max-width:560px;margin:64px auto;padding:24px;'
            'color:#243b32;background:#f6f8f5}h1{font-size:32px}'
            'a{display:block;padding:16px;background:#206344;color:white;'
            'border-radius:12px;text-align:center;text-decoration:none}'
            '</style><h1>대화동행 테스트 앱</h1>' + action +
            '<p>Android 휴대폰에서 다운로드한 파일을 열어 설치해주세요. '
            '설치 시 이 브라우저의 앱 설치 허용이 필요할 수 있습니다.</p>'
            '<p>앱을 열면 공용 테스트 서버에 자동으로 연결됩니다. '
            '복약 알림과 음성 기능은 앱에서 권한을 허용한 뒤 확인해주세요.</p>'
            '<p>팀 테스트용 링크입니다. 팀 안에서만 공유해주세요.</p></html>'
        )

    @app.get("/install/{code}/app.apk")
    async def apk(code: str):
        if not matches(code, download) or not apk_path.is_file():
            return Response(status_code=404)
        return FileResponse(
            apk_path, media_type="application/vnd.android.package-archive",
            filename="daehwa-donghaeng-test.apk",
        )

    @app.api_route(
        "/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
    )
    async def proxy(path: str, request: Request):
        if not matches(request.headers.get("authorization", ""), f"Bearer {access}"):
            return JSONResponse(status_code=401, content={
                "code": "TEST_ACCESS_DENIED",
                "message": "공용 테스트 서버에 연결할 수 없습니다. 최신 테스트 앱을 설치해주세요.",
            })
        if "\\" in path or any(part in (".", "..") for part in path.split("/")):
            return Response(status_code=404)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                return JSONResponse(status_code=413, content={
                    "code": "IMAGE_TOO_LARGE", "message": "요청 크기가 너무 큽니다.",
                })
            body.extend(chunk)
        headers = {
            key: value for key, value in request.headers.items()
            if key.lower() in ("x-device-id", "content-type", "accept")
        }
        headers["accept-encoding"] = "identity"
        try:
            result = await request.app.state.backend.request(
                request.method,
                httpx.URL(path="/api/v1/" + path, query=request.scope["query_string"]),
                content=bytes(body), headers=headers,
            )
        except httpx.HTTPError:
            return JSONResponse(status_code=503, content={
                "code": "SERVER_UNAVAILABLE", "message": "서버 연결을 다시 시도해주세요.",
            })
        return Response(
            result.content, status_code=result.status_code,
            headers={"content-type": result.headers.get("content-type", "application/json")},
        )

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("base_url")
    commands.add_parser("run")
    commands.add_parser("links")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.base_url)
        return
    config = json.loads(CONFIG.read_text())
    if args.command == "links":
        print("API: " + config["base_url"] + "/api/v1")
        print("설치: " + config["base_url"] + "/install/" + config["download_token"])
        return
    uvicorn.run(
        create_app(config), host="127.0.0.1", port=8099,
        access_log=False, server_header=False, limit_concurrency=64,
    )


if __name__ == "__main__":
    main()
