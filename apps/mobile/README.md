# Flutter 앱 연동 자리

Flutter 코드는 이 폴더에 추가합니다.

- Android 에뮬레이터 API: `http://10.0.2.2:8090/api/v1`
- 앱 최초 실행 시 UUID v4를 한 번 생성해 로컬 저장합니다.
- `POST /users/bootstrap`의 `device_id`와 이후 `X-Device-ID` 헤더에 같은 값을 사용합니다.
- 음성은 앱에서 STT로 텍스트화한 뒤 채팅 API에 보냅니다.
- 서버가 반환한 AI 텍스트는 앱에서 TTS로 재생합니다.
- 이미지 업로드 필드명은 `image`, 허용 형식은 JPEG/PNG, 최대 크기는 10MiB입니다.
