# 키 입력 후 실행과 구현 범위

2026-09-22, Backend `4c8def1` / Frontend·AI `21ba1c6` 이후의 로컬 변경 기준.
초기 MVP 02/미결정사항 06 원본은 저장소에 없으므로 v2.1 화면설계·플로우와
현재 계약에 맞췄다. 아래 내용이 과거 통합 보고서의 미구현 항목을 대체한다.

자신의 PC에서 Android 앱과 서버를 함께 실행하려면
[로컬 Android 실행 안내](local-android.md)를 따른다. 아래 스크립트는 미니 PC에
준비한 Ubuntu 환경용이다.

## 이 작업 환경에서 실행

백엔드 저장소의 `.env`에서 제공자를 선택하고 키 두 개를 입력한다.
`feature/gemini-integration`의 로컬 `.env`는 이미 Gemini를 선택하도록 구성했다.
파일은 Git에서 제외되어 있고 앱에 키가 포함되지 않는다.

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
DATA_GO_KR_SERVICE_KEY=...
```

Gemini OCR·대화·분석 기본 모델은 `gemini-3.8-flash`이며 `GEMINI_OCR_MODEL`,
`GEMINI_CHAT_MODEL`로 변경한다. Claude는 `LLM_PROVIDER=anthropic`과
`ANTHROPIC_API_KEY`를 사용하고 모델은 기존 `OCR_MODEL`, `CHAT_MODEL`로 지정한다.
선택한 LLM 키만 필요하며 DUR 키는 공통이다.
[Gemini 연동 상세](../../daehwa-donghaeng-frontend/client-repo/docs/contract/gemini.md)

```sh
cd daehwa-donghaeng
./scripts/start_local.sh --check
./scripts/start_local.sh
# 별도 터미널
./scripts/run_web.sh
# 브라우저: http://127.0.0.1:3000
```

Python 가상환경과 로컬 PostgreSQL 도구를 준비해 두었다. `start_local.sh`는
PostgreSQL → 마이그레이션 → AI → Backend를 시작하며 Ctrl+C로 종료한다.
API는 `http://localhost:8090/api/v1`, Swagger는 `/docs`다. 로컬 서버는
127.0.0.1에만 바인딩한다. DB·로그는 Git에서 제외한 `.local/development/`에 남는다.

다른 Ubuntu 24.04 x86_64 개발 PC에서는 `uv` 설치 후 `./scripts/setup_local.sh`를
한 번 실행한다. 시스템 DB 서비스는 변경하지 않는다. 웹 개발에는 Flutter SDK가
필요하며 `FLUTTER_BIN`으로 지정할 수 있다. 이 작업 환경에는 SDK도 준비했다.

키 없이 동일 코드 경로를 재현하려면 `./scripts/start_local.sh --fixture`를 사용한다.
`--llm-provider gemini` 또는 `--llm-provider anthropic`으로 제공자를 지정할 수 있다.
별도 `.local/fixture/` DB를 쓰며 외부 LLM·식약처 HTTP 응답만 가상 데이터로
교체한다. 운영 앱 코드에 fallback을 넣지 않았다. fixture 모드와 실제 모드는
동시에 같은 포트를 사용하지 않으며 실제 키 검증 결과로 간주할 수 없다.

Android 개발 APK는 `client-repo/app/build/app/outputs/flutter-apk/app-debug.apk`다.
USB 디버깅으로 연결한 기기에서 다음과 같이 로컬 서버에 연결한다.

```sh
adb reverse tcp:8090 tcp:8090
adb install -r ../daehwa-donghaeng-frontend/client-repo/app/build/app/outputs/flutter-apk/app-debug.apk
```

이 개발 APK의 주소는 `http://127.0.0.1:8090/api/v1`이다. 일반 `flutter run`의
Android 기본 주소는 `http://10.0.2.2:8090/api/v1`이며, 다른 서버는
`--dart-define=API_BASE_URL=.../api/v1`으로 지정한다. HTTP 허용은 debug/profile에만
적용했다. 배포용 인증·서명·HTTPS 운영 구성은 이 시연 앱 계약과 별도다.

## 구현한 동작

- 대화: 같은 세션의 최근 완결된 10개 대화 쌍을 LLM에 전달한다. 중복 전송은
  저장된 결과를 반환하고, 같은 전송 ID로 내용을 바꾸면 409를 반환한다.
- 복약: 기존 일정 불러오기·수정·전체 취소, 복용 종료, 날짜별 기록 조회.
  일정 변경 후에도 과거 응답을 보존하고 같은 약·시각의 중복 이벤트를 방지한다.
- 등록: request_id와 scan_id로 중복 저장을 방지하고 응답 유실 시 등록 결과를
  조회한다. 약 이름을 바꾸면 이전 품목·성분 식별자를 지운다.
- Android 알림: 권한 요청, 매일 한국 시간 예약, 일정 삭제·복용 종료 시 취소,
  OS 재부팅 수신기, 알림을 통한 복약/대화 진입. 정확한 알람 권한이 없으면
  지연 가능한 예약과 안내를 사용한다. 웹에는 OS 백그라운드 알림이 없다.
- DUR: 병용금기, 노인주의, 효능군중복. 품목이 모호하거나 일부 조회가 실패하면
  `unverified`이며 '조회된 주의사항 없음'으로 처리하지 않는다. 활성 약 30개를
  넘으면 명시적으로 거절한다. 쌍 비교가 누락되는 임의 분할은 하지 않는다.
- 온보딩·설정: 분석과 보호자 공유는 각각 선택 동의이며 전부 OFF로도 이용 가능하다.
  공유 항목은 복약·감정 표현·대화 표현으로 나뉜다.
- 분석: 동의 후 시작한 종료 세션만 분석한다. 발화 수·평균 글자 수·어휘 다양성·
  제한된 감정 표현 숫자만 저장한다. 외부 분석 실패 시 정량 지표를 보존하고 재시도한다.
  최근 7일과 이전 7일 각각 3세션·10발화 이상일 때 비교한다. 감정 비교에는
  confidence 0.5 이상인 분석 3회씩이 추가로 필요하다. 이 값들은 구현상 충분성
  기준이며 임상 기준이 아니다. 진단·인지장애 판정을 생성하지 않는다.
- 보호자: 24시간 유효한 1회용 초대 코드, 수락, 연결 목록, 철회, 리포트 미리보기와
  보호자 조회. 리포트에는 허용된 집계만 나오며 대화 원문·음성은 포함되지 않는다.
  이메일 발송 서비스 없이 초기 계획의 대시보드 방식으로 구현했다.
- 철회: 분석 동의 철회는 기존 분석을 삭제하고 이전 세션 재분석을 막는다.
  공유 철회는 초대·연결을 해제한다. 동의 변경 이력을 저장한다.

## 추가 계약

정확한 스키마는 실행 중인 `/docs`를 기준으로 한다.

| API | 용도 |
| --- | --- |
| GET `/api/v1/medication-schedules` | 기기의 알림 동기화용 활성 일정 |
| GET/PUT `/api/v1/medications/{id}/schedules` | 조회·변경, `schedules: []`로 취소 |
| GET `/api/v1/medication-events?start=YYYY-MM-DD&end=YYYY-MM-DD` | 오늘까지 최대 93일 |
| GET `/api/v1/medication-registrations/{request_id}` | 응답 유실 복구 |
| PUT `/api/v1/users/me/consents` | 분석·공유·항목별 동의·온보딩 완료 |
| PUT `/api/v1/users/me/reminders` | 저녁 대화 알림 ON/OFF·시각 |
| GET `/api/v1/insights` | 본인 지표와 미완료 분석 ID |
| POST `/api/v1/chat/sessions/{id}/analysis` | 동의된 종료 세션 분석 재시도 |
| POST `/api/v1/caregivers/invitations`, `/accept` | 초대·수락 |
| GET `/api/v1/caregivers/links`, DELETE `/links/{id}` | 목록·철회 |
| GET `/api/v1/caregivers/report-preview`, `/links/{id}/report` | 본인/보호자 리포트 |
| POST AI `/v1/analysis/session` | `utterances` → `mood_score`, `confidence` |

기존 AI `/v1/chat/reply`에 선택적 `history`가 추가됐다. user/assistant 순서의
완결된 쌍만 허용하며 최대 20메시지, 각각 4,000자다. 기본값은 빈 목록이다.

DUR는 [식약처 공식 서비스 명세](https://www.data.go.kr/data/15059486/openapi.do)의
`getUsjntTabooInfoList03`, `getOdsnAtentInfoList03`, `getEfcyDplctInfoList03`를 사용한다.

## 검증 실행

```sh
cd apps/backend
.venv/bin/python -m pytest
# 실제 PostgreSQL URL을 주면 테스트 전용 schema 생성·삭제로 격리한다.
INTEGRATION_DATABASE_URL=postgresql+psycopg://... .venv/bin/python -m pytest -m integration

cd ../../../daehwa-donghaeng-frontend/client-repo/ai
.venv/bin/python -m pytest
cd ../app
flutter analyze
flutter test
```

`test_e2e_remote.py`는 Claude/Gemini 각각 실제 Backend·AI와 외부 API 클라이언트를
실행한다. 외부 HTTP만 fixture로 교체하고
OCR→DUR 세 종류→복약→문맥 대화→분석→공유→철회를 확인한다.
`tests/serve_e2e.py`는 같은 격리 스택을 앱 테스트에 제공한다.
`app/tool/web_e2e.py`는 Playwright Chromium으로 실제 렌더링된 앱을 조작한다.

키 입력 뒤 실제 약봉투 사진을 넣어 외부 서비스까지 확인한다:

```sh
apps/backend/.venv/bin/python apps/backend/scripts/smoke_test.py \
  http://localhost:8090 --expected-provider remote --image /path/to/label.jpg
```

실제 키의 권한·사용량·선택 모델 접근, 사진 인식 품질, 실기기 카메라·음성 인식·
절전 상태 알림 도착은 실제 서비스/기기에서 확인해야 한다. 이 항목의 성공은
키 없는 자동 테스트나 APK 빌드 성공으로 주장하지 않는다.


### 이 환경의 Android 실행 제한

하드웨어 가속 장치(`/dev/kvm`)가 없어 API 36 에뮬레이터를 소프트웨어 방식으로
실행했다. 시스템 초기화가 오래 걸렸고 `device is still booting`으로 APK 설치가
완료되지 않았다. 따라서 Android 네이티브 E2E·실제 알림 도착은 통과로 기록하지
않는다. 코드의 예약·권한 거부·취소 테스트와 APK 빌드는 통과했다.
`client-repo/app/tool/android_reminder_smoke.py`는 부팅을 마친 새 테스트 에뮬레이터에서
실제 예약·도착·취소를 확인할 실행 스크립트이며 이 호스트에서는 아직 미검증이다.
