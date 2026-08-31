# API 계약

- Swagger UI: `http://localhost:8090/docs`
- OpenAPI JSON: `http://localhost:8090/openapi.json`
- Android 에뮬레이터 base URL: `http://10.0.2.2:8090/api/v1`
- bootstrap 이후 모든 `/api/v1` 요청에 `X-Device-ID` 헤더가 필요합니다.

## 연동 순서

1. `POST /api/v1/users/bootstrap`
2. `POST /api/v1/medication-scans?scenario=success`
3. OCR 결과를 확인한 뒤 `POST /api/v1/medications/batch`
4. `POST /api/v1/dur-checks?scenario=none`
5. `PUT /api/v1/medications/{id}/schedules`
6. `GET /api/v1/medication-events/today`
7. `PUT /api/v1/medication-events/{id}/response`
8. `POST /api/v1/chat/sessions`
9. `POST /api/v1/chat/sessions/{id}/messages`
10. `POST /api/v1/chat/sessions/{id}/end`

`scenario`는 개발 환경에서만 사용하는 mock 제어값입니다. OCR은 `success`, `empty`, `failure`, DUR은 `none`, `warning`, `failure`를 지원합니다.
