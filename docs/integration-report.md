# 서버 통합 검증 보고서 — 2026-09-09

HTTP 통합 기반 구현과 자동 테스트·인수인계 문서 작성을 완료했다.
실제 AI mock HTTP 호출과 PostgreSQL 저장을 검증했다.
Docker Compose 설정은 검증했지만 이 실행 환경에는 Docker 엔진이 없어
**컨테이너 이미지 빌드 및 PostgreSQL 17 Compose 기동은 미검증**이다.

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| `PROVIDER_MODE=mock python -m pytest -m 'not integration'` | **93 passed** — 기존 API 테스트, Mock 회귀, Remote 계약 및 API 장애·재시도 |
| `PROVIDER_MODE=mock INTEGRATION_DATABASE_URL=<test-postgresql-url> python -m pytest` | **96 passed, 2 warnings**, 11.43초 — 최종 전체 테스트 |
| 실제 HTTP 통합만 PostgreSQL로 실행 | **3 passed** — remote 흐름/AI 중단, 내부 mock 흐름, 실제 read timeout |
| 실제 HTTP 통합만 임시 SQLite로 실행 | **3 passed** — PostgreSQL 없는 개발 환경의 fallback 확인 |
| AI `python -m pytest` | **7 passed, 2 warnings** — 기존 AI 계약 테스트 |
| Backend `ruff check .` | **All checks passed** |
| AI `ruff check .` | **All checks passed** |
| 양쪽 `git diff --check` | 통과 |
| 양쪽 Compose 진입점 × Backend mock/remote | 설정 병합, 실제 build context 경로, DB/AI service_healthy 의존성 검증 통과 |
| 별도 형제 저장소로 분리한 임시 폴더 구조 | AI_BUILD_CONTEXT / BACKEND_BUILD_CONTEXT override 양쪽 검증 통과 |
| 코드·Compose 내 개인 절대경로 확인 | 개인 Windows/Linux 절대경로 추가 없음 |
| Docker 이미지 빌드/컨테이너 기동 | **미실행: Docker 엔진 미설치** |

실행 환경: Python 3.13.15, PostgreSQL 16.15 임시 클러스터,
FastAPI 0.141.1, httpx 0.28.1, Pydantic 2.13.5, SQLAlchemy 2.0.52,
pytest 8.4.2, Ruff 0.16.6, Docker Compose CLI 2.39.4.
경고 2개는 Starlette TestClient의 httpx 사용 및 AnyIO BlockingPortal alias에 대한
의존 라이브러리 deprecation 경고다. 테스트 실패는 없다.

실행 명령의 `<test-postgresql-url>`에는 로컬 테스트 DB URL을 사용했다.
통합 테스트는 개별 임시 schema에 Alembic migration을 적용하고 종료 시 제거한다.
시스템 DB/기존 사용자 데이터를 변경하지 않았다. 테스트용 Python 도구와 PostgreSQL은
작업 저장소 밖 임시 디렉터리에 준비했다.

## 실제로 확인한 흐름과 DB 저장

독립 프로세스 `test client → Backend uvicorn → AI mock uvicorn → PostgreSQL`로 실행했다.
AI subprocess에는 API 키를 전달하지 않았고 AI 모드는 mock, Backend는 remote였다.

1. 새 device ID로 사용자 bootstrap.
2. 유효 PNG multipart를 Backend에 업로드하고 AI의 `/v1/ocr/prescription-label` 호출.
3. OCR scan `provider=remote`, `status=success`, result JSON 저장.
4. 확인한 OCR 약 2건 저장 및 `/medications` 재조회, `source=ocr` 확인.
5. `/v1/dur/check` 호출, DUR snapshot/검사 결과/경고 1건 저장 및 검사 API 재조회.
6. 일정 생성, 오늘 이벤트 조회, `taken` 기록 및 재조회.
7. `/v1/chat/reply`로 첫 인사와 사용자 발화 응답 수신.
8. 채팅 DB의 역할 순서 `assistant/user/assistant`, 횟수 1, 종료 상태 확인.
9. 동일 `client_message_id` 재전송 시 같은 메시지 쌍 반환.
10. PostgreSQL에서 동시 세션 생성은 같은 활성 세션을, 동시 메시지 재전송은 같은 메시지 쌍을 반환.
11. AI 프로세스 종료 후 OCR/DUR/Chat은 정의된 502 반환, 실패 DUR 기록과 채팅 무변경 확인.
12. 실제 AI mock 앞 프록시에서 응답을 1초 지연하고 Backend timeout을 0.5초로 설정:
    OCR/DUR/채팅 인사/일반 메시지 모두 정의된 502, 채팅 메시지·횟수 무변경 확인.

별도 API 장애 테스트는 timeout·연결 오류·HTTP 오류·JSON 오류·필수 필드 누락에 대해
실패 후 복구 및 같은 메시지 ID의 재시도를 검증한다. 응답 검증 오류가 일반 500으로
빠지거나 사용자 메시지만 남는 상태를 방지한다.

## 핵심 설계 판단

- **Protocol/dataclass/API/DB 스키마 유지.** 기존 Mock 구현을 그대로 두고 HTTP 어댑터를 추가했다.
  OCR의 기존 MedicationDraft 제약을 재사용하고 DUR도 DB 문자열 제한과 요청 ID를 검증한다.
- **설정은 Provider 생성 시 주입.** import 시점의 전역 Mock 인스턴스를 제거하고
  FastAPI dependency factory가 Settings를 받아 선택한다. 테스트는 dependency override 또는
  `get_settings.cache_clear()`로 환경을 격리하며 모듈 재로딩이 필요 없다.
- **실패 경계 통일.** HTTP/JSON/검증 오류를 ProviderError(RuntimeError)로 묶어 기존 OCR/DUR
  오류 처리를 유지하고 채팅에도 502를 추가했다. AI 원문 오류를 사용자에게 노출하지 않는다.
- **채팅 원자성.** Provider 성공 전 메시지/횟수를 변경하지 않는다. 실패는 rollback한다.
  PostgreSQL 사용자/세션 행 잠금으로 원격 호출 중 동시 생성·전송·종료를 직렬화한다.
  저장된 중복은 AI 호출 전에 조회한다. 새로운 DB 필드나 migration은 추가하지 않았다.
- **동기 Protocol 유지.** context-managed httpx.Client로 자원을 정리한다.
  async OCR 업로드 경로는 Provider 호출만 threadpool에서 실행한다.
- **경로 이식성.** 현재 `client-repo` 중첩 구조를 기본값으로 제공하고 별도 저장소로 이동하면
  build context 환경변수만 바꾼다. 통합 Compose는 AI 포트를 호스트에 공개하지 않는다.
- **모드 분리.** Backend remote + AI mock이 키 없는 통합 기본 조합이다.
  AI 실제 구현이 계약을 유지하면 Backend 코드를 다시 바꾸지 않고 환경변수와 검증으로 연결한다.

## 변경 파일

Backend 저장소 `daehwa-donghaeng`:

| 파일 | 변경 |
| --- | --- |
| `apps/backend/app/config.py` | mock/remote 검증, AI URL/timeout |
| `apps/backend/app/providers.py` | HttpOCR/DUR/Chat, JSON 검증, ProviderError, dependency factory |
| `apps/backend/app/api/medications.py` | Provider 주입, OCR threadpool, 기존 오류 계약 유지 |
| `apps/backend/app/api/chat.py` | Provider 주입, 502, 원자적 저장/rollback, PostgreSQL 잠금 |
| `apps/backend/pyproject.toml` | httpx runtime 이동, integration pytest marker |
| `apps/backend/Dockerfile` | runtime smoke script 포함 |
| `apps/backend/scripts/smoke_test.py` | 전 흐름/재조회/멱등성 검증, 기대 모드 및 실제 이미지 옵션 |
| `apps/backend/tests/conftest.py` | 설정 cache 및 dependency 격리 |
| `apps/backend/tests/test_providers.py` | Mock 회귀, HTTP 요청/응답/오류/설정 계약 |
| `apps/backend/tests/test_provider_errors.py` | API 502, 실패 DB 기록, 채팅 원자성·복구·멱등성 |
| `apps/backend/tests/test_remote_integration.py` | 실제 HTTP + migration/DB 조회 + 중단/지연/PG 동시성 |
| `apps/backend/tests/server_helpers.py`, `apps/backend/tests/__init__.py` | 프로세스·지연 프록시 테스트 도구 |
| `compose.yaml`, `compose.integration.yaml` | 모드 설정 및 DB+Backend+AI 실행 |
| `.env.example`, `.gitignore` | 환경변수 안내, 설치 산출물 egg-info 제외 |
| `README.md`, `docs/api/README.md`, `docs/chat-session.md`, `docs/architecture.md` | 현재 연동 구조·오류 계약 반영 |
| `docs/server-integration.md` | 실행·검증·FE/AI 계약·실제 구현 수령 체크리스트 |
| `docs/integration-report.md` | 이 보고서 |

FE 전달 저장소 `daehwa-donghaeng-frontend`:

아래 파일은 로컬 변경안으로 보존하며 GitHub에 push하지 않는다.
이번 전달 대상은 BE 역할의 `daehwa-donghaeng` 저장소뿐이다.
FE 담당자가 변경안을 검토·반영하기 전에는 Backend 저장소의 통합 Compose를 사용한다.

| 파일 | 변경 |
| --- | --- |
| `client-repo/compose.integration.yaml` | Backend 중첩 상대경로 수정, 모드/context/timeout, DB volume, Backend healthcheck |
| `client-repo/.env.example` | 모드/context/timeout 설정 예시 |
| `client-repo/README.md` | 현재 경로와 통합 실행 명령 |
| `client-repo/docs/contract/ai-service.md` | 구현된 HTTP 검증·502·미결정 사항 반영 |
| `client-repo/docs/contract/backend-integration.md` | FE/AI용 서버 연결 인수인계 |

작업 전 양쪽 `git status --short`는 깨끗했다. 기존 Flutter/AI 구현 파일,
Backend 모델 및 migration은 변경하지 않았다.

## 남은 외부 의존성 및 결정 필요 사항

- Docker 엔진 환경에서 `docker compose -f compose.yaml -f compose.integration.yaml up --build --wait`
  및 문서의 remote smoke를 실행하여 **이미지 빌드와 PostgreSQL 17 컨테이너 기동을 최종 확인**해야 한다.
  이번 보고서의 PostgreSQL 실제 검증 버전은 16.15다.
- 실제 Claude OCR·식약처 DUR·약명 매핑·LLM은 AI 담당 구현이 필요하다.
  현재 AI의 실제 모드 경로는 501 TODO이며 단순 환경변수 변경으로 구현을 대신하지 않는다.
- FE는 ApiClient/OCR Repository를 연결해야 한다. Flutter 화면·STT/TTS·실기기는 이번 범위 밖이다.
- **결정 1: LLM에 이전 대화 history를 보낼지와 그 형식.** 현재는 보내지 않는다.
- **결정 2: 약 용량·복용기간 DB 필드명, 단위, 형식.** 현재 필드가 없으며 임의로 추가하지 않았다.
- 기존 AI DUR 요청 schema는 1~30개 약을 허용하지만 Backend의 누적 활성 약 개수에는 같은 제한이 없다.
  **30개 초과 DUR 처리 정책은 추가 합의가 필요**하다. Backend 외부 API를 임의로 제한하거나
  전체 약 간 상호작용을 놓칠 수 있는 분할 검사를 구현하지 않았다. 현 계약에서 AI 422는 Backend 502로 처리된다.

상세 실행·복구 절차와 담당자별 체크리스트는 [서버 통합 인수인계](server-integration.md)를 따른다.
