# BE 아키텍처

```mermaid
flowchart LR
  APP[Flutter Android 앱] -->|REST JSON / multipart\nX-Device-ID| API[FastAPI]
  API --> DB[(PostgreSQL)]
  API --> OCR[OCRProvider]
  API --> DUR[DURProvider]
  API --> CHAT[ChatProvider]
  OCR -. 시연 .-> OM[Mock OCR]
  DUR -. 시연 .-> DM[Mock DUR]
  CHAT -. 시연 .-> CM[Mock AI]
  OCR -. 추후 .-> CLAUDE[Claude API]
  DUR -. 추후 .-> PUBLIC[식약처 공공데이터 API]
  CHAT -. 추후 .-> LLM[대화 LLM]
```

## 경계

- Flutter는 촬영, 마이크, STT, TTS를 담당합니다.
- 백엔드는 사용자 식별, 약·복약 데이터, DUR 결과, 채팅 세션과 텍스트 메시지를 담당합니다.
- 음성 파일은 백엔드로 전송하지 않습니다.
- 약봉투 이미지는 요청 처리 중 메모리에서만 사용하고 DB 또는 파일시스템에 저장하지 않습니다.
- 모든 외부 연동은 provider 인터페이스 뒤에 두며 `PROVIDER_MODE=mock`이 기본입니다.

## 실행 환경

- 1차 시연: Android 에뮬레이터 → `10.0.2.2:8010`
- 백엔드: FastAPI 단일 서비스
- DB: PostgreSQL
- 구성: Docker Compose
- DB 시각: UTC, 사용자 일정 기준: `Asia/Seoul`
