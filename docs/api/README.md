# API 계약

- Swagger UI: `http://localhost:8090/docs`
- OpenAPI JSON: `http://localhost:8090/openapi.json`
- Android 에뮬레이터 base URL: `http://10.0.2.2:8090/api/v1`
- bootstrap 이후 모든 `/api/v1` 요청에 `X-Device-ID` 헤더가 필요합니다.

## 연동 순서

1. `POST /api/v1/users/bootstrap`
2. `POST /api/v1/medication-scans?scenario=success`
3. OCR 결과를 확인한 뒤 `POST /api/v1/medications/batch`
   이후 `GET /api/v1/medications`로 저장된 목록을 조회합니다.
4. `POST /api/v1/dur-checks?scenario=none`
5. `PUT /api/v1/medications/{id}/schedules`
6. `GET /api/v1/medication-events/today`
7. `PUT /api/v1/medication-events/{id}/response`
8. `POST /api/v1/chat/sessions`
9. `POST /api/v1/chat/sessions/{id}/messages`
10. `POST /api/v1/chat/sessions/{id}/end`

`scenario`는 개발 환경에서만 사용하는 mock 제어값입니다. OCR은 `success`, `empty`, `failure`, DUR은 `none`, `warning`, `failure`를 지원합니다.

`PROVIDER_MODE=remote`에서는 `scenario`를 AI 서버에 보내지 않습니다. Flutter는 이를 생략합니다.
OCR/DUR/Chat Provider의 연결 실패, timeout, HTTP 오류, 응답 검증 오류는 각각
`502 OCR_PROVIDER_ERROR`, `502 DUR_PROVIDER_ERROR`, `502 CHAT_PROVIDER_ERROR`입니다.
오류 본문은 기존 `{code, message, details}` 형식입니다.

채팅 복구는 `GET /api/v1/chat/sessions/current`, DUR 재조회는
`GET /api/v1/dur-checks/{id}`를 사용합니다.
필드·실행 명령·재시도 규칙은 [서버 통합 인수인계](../server-integration.md)에 정리되어 있습니다.
