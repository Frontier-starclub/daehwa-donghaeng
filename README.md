# 대화동행 · 프런티어

Flutter 앱과 FastAPI 백엔드를 함께 관리하는 팀 모노레포입니다. 현재 백엔드는 외부 API 키 없이도 OCR, DUR, AI 채팅 흐름을 시연할 수 있도록 mock provider를 사용합니다.

## 빠른 실행

1. Docker Desktop을 실행합니다.
2. 저장소 루트에서 `docker compose up --build`를 실행합니다.
3. Swagger UI는 `http://localhost:8010/docs`에서 확인합니다.
4. Android 에뮬레이터의 API base URL은 `http://10.0.2.2:8010/api/v1`입니다.

로컬 Python으로 실행하려면 `apps/backend`에서 다음을 실행합니다.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## 저장소 구조

- `apps/backend`: FastAPI, PostgreSQL 모델, migration, 테스트
- `apps/mobile`: Flutter 팀원을 위한 연동 안내와 향후 앱 코드 위치
- `docs/api`: API 계약과 예제
- `docs/product`: 기존 기획 문서 안내
- `docs/architecture.md`: 시스템 구조
- `docs/erd.md`: 데이터 모델
- `docs/chat-session.md`: 채팅 세션 규칙

## 개발 원칙

- `main`은 시연 가능한 상태를 유지합니다.
- 기능 작업은 `feature/<이름>` 브랜치에서 진행합니다.
- 실제 `.env`, API 키, 음성 및 약봉투 원본 이미지는 커밋하지 않습니다.
- mock 응답은 의학적 사실이 아닌 UI·연동 검증용 데이터입니다.
