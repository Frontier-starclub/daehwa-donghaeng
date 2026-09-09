# 서버 통합 실행 및 인수인계

현재 작업 폴더를 기준으로 경로를 정리했다. Windows 개인 절대경로에 의존하지 않는다.

```text
<workspace>/
├── daehwa-donghaeng/                         # Backend 저장소
└── daehwa-donghaeng-frontend/                # 현재 FE 전달 저장소
    ├── backend-repo-docs/docs/contract/backend-adapter-request.md
    └── client-repo/                         # 실제 Flutter·AI 소스
        ├── ai/
        ├── docs/contract/ai-service.md
        └── compose.integration.yaml
```

```mermaid
sequenceDiagram
    participant FE as Flutter / smoke client
    participant BE as Backend :8090
    participant AI as AI service :8100
    participant DB as PostgreSQL
    FE->>BE: bootstrap, X-Device-ID
    FE->>BE: OCR image (multipart)
    BE->>AI: POST /v1/ocr/prescription-label
    AI-->>BE: items
    BE->>DB: scan result
    BE-->>FE: scan_id, editable items
    FE->>BE: 사용자 확인 후 medications/batch
    BE->>DB: medications
    FE->>BE: dur-checks
    BE->>AI: POST /v1/dur/check
    AI-->>BE: warnings
    BE->>DB: DUR snapshot, result, warnings
    FE->>BE: schedules, events/today, response
    BE->>DB: schedules, events, taken/not_taken
    FE->>BE: chat session, message
    BE->>AI: POST /v1/chat/reply
    AI-->>BE: content
    BE->>DB: session, message pair, count (one transaction)
```

## 환경변수

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `PROVIDER_MODE` | `mock` | Backend: `mock`은 내부 Mock, `remote`는 HTTP 어댑터 3개 사용. 다른 값은 시작 실패 |
| `AI_SERVICE_URL` | `http://ai:8100` | Backend가 접근할 AI HTTP(S) URL. 로컬 프로세스는 `http://127.0.0.1:8100` |
| `AI_SERVICE_TIMEOUT` | `30` | 초 단위 양수. httpx connect/read/write/pool 각각의 timeout이며 총 요청 시간 제한은 아님 |
| `AI_PROVIDER_MODE` | `mock` | Compose에서 AI 컨테이너의 `PROVIDER_MODE`로 전달. Backend 모드와 별개 |
| `AI_BUILD_CONTEXT` | `../daehwa-donghaeng-frontend/client-repo/ai` | Backend Compose 기준 AI Dockerfile 디렉터리 |
| `DATABASE_URL` | `.env.example` 참조 | 로컬 Backend용 PostgreSQL SQLAlchemy URL. Compose는 `db:5432` 사용 |
| `APP_ENV` | `development` | 기존 설정 유지 |
| `ANTHROPIC_API_KEY`, `DATA_GO_KR_SERVICE_KEY` | 비어 있음 | 통합 Compose에서 AI 컨테이너에만 전달. AI mock에는 불필요 |
| `AI_SOURCE_DIR` | 현재 전달 폴더의 `client-repo/ai` | 자동 HTTP 통합 테스트용 AI 소스 디렉터리 |
| `INTEGRATION_DATABASE_URL` | 미설정 | 자동 통합 테스트용 PostgreSQL URL. 미설정이면 임시 파일 SQLite 사용 |

Backend 루트의 `.env.example`을 `.env`로 복사할 수 있다. `.env.example`에는
`PROVIDER_MODE=mock`이므로 remote 실행 때 **명시적으로 remote를 설정**한다.
Compose integration overlay 자체의 기본값은 remote이나 `.env` 값이 우선한다.
환경변수 변경은 Backend 재시작/컨테이너 재생성 후 적용된다.

## 1. 내부 Mock 실행

Backend 저장소 루트에서:

```bash
PROVIDER_MODE=mock docker compose up --build --wait
# 실행 중인 컨테이너의 runtime httpx를 사용하므로 호스트 Python 설치 불필요
docker compose exec backend python scripts/smoke_test.py http://localhost:8000 --expected-provider mock
```

PowerShell에서는 첫 줄을 다음 두 줄로 실행한다.

```powershell
$env:PROVIDER_MODE = "mock"
docker compose up --build --wait
```

AI 서비스가 없어도 동작한다. 기존 `scenario` 응답은 그대로다.
OCR: `success/empty/failure`, DUR: `none/warning/failure`.

## 2. Backend → AI mock HTTP 통합 실행

Backend 저장소 루트에서:

```bash
PROVIDER_MODE=remote AI_PROVIDER_MODE=mock docker compose -f compose.yaml -f compose.integration.yaml up --build --wait
docker compose -f compose.yaml -f compose.integration.yaml exec backend python scripts/smoke_test.py http://localhost:8000 --expected-provider remote
```

PowerShell:

```powershell
$env:PROVIDER_MODE = "remote"
$env:AI_PROVIDER_MODE = "mock"
docker compose -f compose.yaml -f compose.integration.yaml up --build --wait
docker compose -f compose.yaml -f compose.integration.yaml exec backend python scripts/smoke_test.py http://localhost:8000 --expected-provider remote
```

DB와 AI healthcheck가 통과한 뒤 Backend가 시작하며, Backend 시작 명령이
`alembic upgrade head`를 실행한다. Backend만 호스트 `8090` 포트를 열고,
AI는 Compose 내부 `http://ai:8100`으로 호출한다. 키 없이 세 Provider가 실제 HTTP를 사용한다.
두 모드 모두 smoke 출력의 `status`가 `ok`여야 하며 `--expected-provider`는 설정 실수를 잡는다.
기본 smoke 이미지는 실제 PNG 1픽셀로 **AI mock 검증용**이다.

`client-repo`가 별도 형제 저장소가 되면 Backend 루트 `.env`에서 이것만 바꾼다.

```dotenv
AI_BUILD_CONTEXT=../client-repo/ai
```

AI Dockerfile이 있는 디렉터리를 지정하며 상대경로 기준은 첫 Compose 파일인
Backend의 `compose.yaml`이다. 경로에 공백이 있으면 셸에서 환경변수 값을 인용한다.

FE 전달 폴더에서도 실행 가능하다. `client-repo` 안에서:

아래 FE 진입점 설명은 이번에 작성한 **로컬 변경안** 기준이다. GitHub push 대상은
Backend 저장소뿐이므로 FE 담당자가 변경안을 반영하기 전에는 위의 Backend Compose 진입점을 사용한다.

```bash
PROVIDER_MODE=remote docker compose -f compose.integration.yaml up --build --wait
python ../../daehwa-donghaeng/apps/backend/scripts/smoke_test.py --expected-provider remote
```

이 진입점의 `BACKEND_BUILD_CONTEXT` 기본값은 `../../daehwa-donghaeng/apps/backend`다.
분리 후에는 `../daehwa-donghaeng/apps/backend`로 변경한다.
`PROVIDER_MODE`가 우선하고, 기존 `BACKEND_PROVIDER_MODE`도 fallback으로 지원한다.
두 Compose 진입점은 서로 다른 프로젝트/DB volume이므로 하나를 선택해 실행한다.
동시에 띄우면 `8090` 포트가 충돌한다. 일반 `down`은 DB volume을 보존한다.

## 3. Docker 없이 로컬 프로세스 실행

Python **3.13 이상**, PostgreSQL과 서로 다른 터미널 2개를 사용한다.
양쪽 Python 패키지명이 모두 `app`이므로 각 소스 디렉터리에서 실행한다.
실제 개발 환경에서는 Backend와 AI의 가상환경도 분리하는 것을 권장한다.

Backend `apps/backend`에서 의존성 설치:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

AI `client-repo/ai`에서 자체 가상환경에 `python -m pip install -e '.[dev]'` 후:

```bash
PROVIDER_MODE=mock uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Backend `apps/backend`에서:

```bash
export DATABASE_URL='postgresql+psycopg://frontier:frontier@127.0.0.1:5432/frontier'
export PROVIDER_MODE=remote
export AI_SERVICE_URL=http://127.0.0.1:8100
export AI_SERVICE_TIMEOUT=30
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

호스트 smoke는 Backend 의존성을 설치한 Python으로 실행한다.

```bash
python scripts/smoke_test.py http://localhost:8090 --expected-provider remote
```

PowerShell은 `source .venv/bin/activate` 대신 `.venv\Scripts\Activate.ps1`,
`export KEY=value` 대신 `$env:KEY = "value"`를 사용한다.

## 4. 자동화 검증

Backend `apps/backend`에서:

```bash
# 기존 API 테스트 + Mock 회귀 + HTTP 계약 + 장애·재시도 검증
PROVIDER_MODE=mock python -m pytest -m 'not integration'
# 실제 Backend 및 AI mock uvicorn 프로세스를 임의의 loopback 포트로 시작
python -m pytest -m integration
# 전체 (현재 전달 폴더 구조이면 AI_SOURCE_DIR 불필요)
PROVIDER_MODE=mock python -m pytest
ruff check .
```

실제 PostgreSQL 저장/동시 재전송 검증:

```bash
INTEGRATION_DATABASE_URL='postgresql+psycopg://frontier:frontier@127.0.0.1:5432/frontier' python -m pytest -m integration
```

테스트는 지정 DB 안에 임의의 `integration_<uuid>` schema를 만들고 Alembic migration을
적용한다. 종료 시 **그 테스트가 만든 schema만** 제거한다. 계정에 schema 생성 권한이 필요하다.
이 URL은 직접 PostgreSQL에 연결하는 테스트용 URL이어야 한다.
SQLite fallback은 HTTP/저장 검증용이며 PostgreSQL 행 잠금 검증은 PG 사용 시에만 실행된다.
AI 소스가 없으면 integration은 명확히 실패한다. Backend 단독 체크아웃은
`-m 'not integration'`을 사용하거나 `AI_SOURCE_DIR`를 지정한다.

통합 테스트는 프로세스 간 실제 HTTP를 사용하며 API 키를 subprocess 환경에서 제거한다.
정상 흐름, DB 재조회, 실제 AI 프로세스 종료, AI mock 앞 지연 프록시를 통한 read timeout을 검증한다.
프로세스와 임시 DB는 테스트 종료 시 정리된다.

AI `client-repo/ai`에서는 별도로:

```bash
python -m pytest
ruff check .
```

## 5. AI 장애 시 외부 계약

| 작업 | Backend 응답 | DB 결과 / 재시도 |
| --- | --- | --- |
| OCR | `502 OCR_PROVIDER_ERROR` | scan `failed`, error_code 저장, 원본 이미지 저장 안 함. 재업로드 가능 |
| DUR | `502 DUR_PROVIDER_ERROR` | check `failed`, snapshot/error_code 저장. 다시 검사 가능 |
| 채팅 첫 인사 | `502 CHAT_PROVIDER_ERROR` | 세션·메시지 생성 안 함. accepted 재요청 가능 |
| 채팅 일반 메시지 | `502 CHAT_PROVIDER_ERROR` | count/activity/messages 변경 없음. 같은 client_message_id로 재시도 |
| 정상 OCR 빈 목록 | 기존 `422 OCR_EMPTY` | scan `empty`, result_json=[] |
| 정상 DUR 빈 목록 | 기존 `201`, status=`no_warnings` | 정상 검사 결과 저장 |

연결 실패, timeout, AI 4xx/5xx(3xx 포함), JSON 파싱 실패, 필수 필드 누락,
잘못된 타입/범위는 모두 위 Provider 오류다. 오류 본문은 기존
`{"code":"...","message":"...","details":null}`이며 AI 오류 원문은 노출하지 않는다.

Compose 실행 후 `docker compose -f compose.yaml -f compose.integration.yaml stop ai`로
중단을 재현할 수 있다. 이미 저장된 약/DUR 조회 및 채팅 중복 요청은 AI 없이 반환된다.
`start ai` 후 같은 채팅 message ID로 재시도한다. 시작 시 healthcheck 의존성은 보장하지만,
실행 중 AI 장애는 Backend의 위 502 처리로 대응한다.
자동 재시도는 없으며, AI가 응답했어도 전송 중 timeout이 나면 다음 재시도에서 AI는 다시 호출될 수 있다.
Backend DB에는 성공한 메시지 쌍만 한 번 저장된다.

## 6. 석윤 FE 인수인계

Flutter 화면/Repository 구현은 이번 변경에 포함하지 않았다. 앱은 AI를 직접 호출하지 않는다.
Backend base URL: 호스트 `http://localhost:8090/api/v1`, Android 에뮬레이터
`http://10.0.2.2:8090/api/v1`. 현재 `UnconfiguredOcrRepository` 연결 작업은 FE 담당이다.
bootstrap 후 같은 device ID를 모든 호출의 `X-Device-ID` 헤더에 보낸다.

| 순서 | Backend API | 주요 요청/응답 연결 |
| --- | --- | --- |
| 1 | `POST /users/bootstrap` | `{device_id, display_name}` → 사용자 |
| 2 | `POST /medication-scans` | multipart `image` JPEG/PNG ≤10MiB → `{id, items, status, provider, created_at}` |
| 3 | 사용자 OCR 결과 확인·수정 | `items`를 그대로 확정하지 말고 사용자 확인을 거친다 |
| 4 | `POST /medications/batch` | `{scan_id: scan.id, items: 확인한 items}` → 약 ID 목록 |
| 5 | `GET /medications` | active 약 목록; `?status=all`로 종료 약 포함 |
| 6 | `POST /dur-checks` | `{medication_ids:[...]}` → 검사 ID, warnings, disclaimer 표시 |
| 7 | `PUT /medications/{id}/schedules` | `{schedules:[{time_slot:"morning",remind_at:"08:00:00"}]}` |
| 8 | `GET /medication-events/today` | 서울 날짜 기준 일정 이벤트 생성 및 조회 |
| 9 | `PUT /medication-events/{id}/response` | `{status:"taken"}` 또는 `not_taken` |
| 10 | `GET /chat/sessions/current` | 재시작 시 활성 세션 복구, 없으면 null |
| 11 | `POST /chat/sessions` | `{decision:"accepted"}` 또는 `declined`; accepted 응답에 첫 인사 |
| 12 | `POST /chat/sessions/{id}/messages` | `{client_message_id:UUID,content:텍스트}` → user_message, assistant_message |
| 13 | `POST /chat/sessions/{id}/end` | 종료는 멱등 |

새 발화마다 새 `client_message_id`를 생성하되 네트워크 재전송/502 재시도에는 같은 값을 쓴다.
재전송 본문도 유지한다. `scenario`는 내부 mock 개발 전용이므로 실제 앱에서는 생략한다.
Remote 어댑터는 받은 `scenario`를 AI에 전달하지 않는다.

## 7. 진수 AI 인수인계: 유지할 계약

Protocol과 dataclass는 유지했다. AI 응답의 알려진 필드는 strict 타입으로 검증하며
추가 필드는 무시한다. nullable 선택 필드는 생략 또는 null 가능하고 추정값을 채우지 않는다.
DB 제약을 넘는 문자열/숫자는 저장 전 Provider 오류로 처리한다.

| 경로 | 필수 요청 필드 | 응답 계약 |
| --- | --- | --- |
| `/health/live` GET | 없음 | `{status:"ok",provider_mode:"mock"}`; healthcheck가 HTTP 200 확인 |
| `/v1/ocr/prescription-label` POST | multipart **image** | `{items:[...]}`; items 필수, 빈 배열 허용 |
| `/v1/dur/check` POST | `{medications:[{id,name,ingredient_code,item_seq}]}` | `{warnings:[...]}`; warnings 필수, 빈 배열 허용 |
| `/v1/chat/reply` POST | `{opening,user_message_count,content}` | `{content: 비어 있지 않은 문자열}` |

OCR item 필드:

| 이름 | 형식 |
| --- | --- |
| `name` | 필수 문자열, 1~100자 |
| `ingredient_name` | null 또는 문자열 ≤200자 |
| `ingredient_code`, `item_seq` | null 또는 문자열 ≤50자; 숫자로 보내지 않는다 |
| `dose_frequency_per_day` | null 또는 정수 1~10 (1일 횟수) |
| `confidence` | null 또는 숫자 0~1 |

DUR warning 필드:

| 이름 | 형식 |
| --- | --- |
| `warning_type` | 필수 문자열 1~40자. 실제 분류 `usjnt_taboo`, `elderly_caution`, `efficacy_overlap`; mock `demo_warning` 허용 |
| `medication_ids` | 필수 문자열 배열. 요청의 `id`를 그대로 돌려준다. 요청에 없는 ID는 Provider 오류 |
| `message` | 필수 문자열 |
| `source_code` | null 또는 문자열 ≤50자 |

DUR 요청에는 `ingredient_name`·용량·기간을 임의로 추가하지 않는다. 현재 AI schema가
한 번에 약 1~30개를 허용하므로 최종 검증 때 30개 초과 활성 약의 처리 정책도 합의해야 한다.
Backend의 기존 약/검사 API 한도를 이번 변경에서 임의로 변경하지 않았다.
`disclaimer`는 Backend가 제공한다.
`/v1/drugs/resolve`는 AI 내부 보조 경로이며 Backend가 별도 호출하지 않는다.

Chat 첫 인사: `{opening:true,user_message_count:0,content:""}`.
일반 응답: `{opening:false,user_message_count:N,content:사용자 문장}`에서 N은
이번 발화를 포함한 성공 예정 횟수(첫 사용자 발화는 1)다.
AI는 상태를 갖지 않으며 세션/순서/멱등성은 Backend 책임이다.
현재 이전 대화 history, 음성, session ID, client_message_id는 AI에 보내지 않는다.

## 8. 실제 AI 구현 수령 후 체크리스트

- [ ] AI 담당자가 실제 OCR/DUR/LLM과 약명 매핑을 구현하고 요청·응답 계약 테스트 통과
- [ ] Backend는 `PROVIDER_MODE=remote` 유지; AI 내부 `AI_PROVIDER_MODE`/키/모델 설정 변경
- [ ] 외부 배포 시 `AI_SERVICE_URL`을 접근 가능한 HTTP(S) 주소로 변경, 연결·timeout 검증
- [ ] 실제 JPEG/PNG 약봉투로 OCR 정확성·빈 결과·오류 확인; 사용자 확인 단계 유지
- [ ] 실제 약 ID/품목기준코드의 DUR 응답, 경고 없는 경우와 외부 장애 구분 검증
- [ ] 외부 지연에 맞춰 `AI_SERVICE_TIMEOUT` 설정 및 502/재시도 테스트 반복
- [ ] `python scripts/smoke_test.py --expected-provider remote --image <검증용-약봉투.png>` 실행
- [ ] DB의 약, DUR snapshot/경고, 일정/복약, 채팅 순서·중복 방지 검증
- [ ] Compose 이미지 빌드와 PostgreSQL 17 컨테이너 기동 검증
- [ ] FE 담당자가 Backend ApiClient/OCR Repository를 연결한 뒤 앱 API 흐름 검증

현재 AI `provider_mode != mock` 경로는 501 TODO이므로 모드만 바꿔도 실제 기능이 생기지는 않는다.
실제 구현이 위 HTTP 계약을 유지하면 Backend Provider 코드는 추가 교체 없이 연결된다.
새 인증/history/schema 계약이 필요하면 별도 합의가 필요하다.

## 명시적인 결정 필요 사항

1. **실제 LLM에 이전 대화 history를 전달할지 여부.** 필요하다면 발화 역할/순서,
   최대 길이·절단 정책 등 요청 형식을 BE·AI가 먼저 합의해야 한다. 이번에는 필드를 추가하지 않았다.
2. **약 용량과 복용기간의 DB 필드명·단위·형식.** 현재 Medication은 약명, 성분 정보,
   품목기준코드, 1일 복용 횟수를 저장한다. 용량과 복용기간은 없다.
   `dose_frequency_per_day`를 용량으로 해석하지 않는다. 합의 전 migration/API 필드를 추가하지 않았다.

실제 Claude OCR, 식약처 DUR, 약명 매칭, LLM, STT/TTS, Flutter 화면,
Android 실기기 검증은 담당자 구현·외부 통합 의존성으로 남는다.
