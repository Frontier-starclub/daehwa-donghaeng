# 로컬 PC에서 Android 앱 테스트

미니 PC에 접속하지 않고 자신의 PC에서 Backend·AI·DB와 Android 앱을 함께 실행한다.
서버는 Docker Compose, 앱은 Flutter와 Android Studio의 에뮬레이터를 사용한다.
두 저장소 모두 `feature/gemini-integration` 브랜치를 받아야 한다.

## 1. 개발 도구 준비

- Git
- Docker Desktop 또는 Docker Engine + Compose 플러그인
- Flutter SDK와 PATH 설정. 이 브랜치의 앱·APK 검증에는 Flutter 3.47.2를 사용했다.
- Android Studio, Android SDK, Android Emulator

Android Studio의 Flutter 플러그인만 설치하면 `flutter` 명령이 제공되지 않는다.
[Flutter 공식 Android 설정](https://docs.flutter.dev/platform-integration/android/setup)에
따라 SDK도 설치한 뒤 다음 명령으로 Android 도구와 라이선스 상태를 확인한다.

```sh
flutter doctor --android-licenses
flutter doctor
```

Android Studio의 Device Manager에서 가상 휴대폰을 만들고 실행한다.

## 2. 같은 상위 폴더에 두 저장소 받기

처음 받는 경우:

```sh
git clone --branch feature/gemini-integration https://github.com/Frontier-starclub/daehwa-donghaeng.git
git clone --branch feature/gemini-integration https://github.com/Frontier-starclub/daehwa-donghaeng-frontend.git
```

이미 받아둔 경우 **각 저장소에서** 다음을 실행한다.

```sh
git fetch origin
git switch feature/gemini-integration
git pull --ff-only
```

폴더 구조:

```text
workspace/
  daehwa-donghaeng/
  daehwa-donghaeng-frontend/
    client-repo/app/
    client-repo/ai/
```

## 3. 서버 환경변수 설정

`daehwa-donghaeng/.env.example`을 같은 폴더의 `.env`로 복사한다.
기존 `.env`가 있다면 복사하지 않고 필요한 설정만 수정한다.
이 실행 방법에서는 Backend 저장소의 `.env` 하나만 사용한다.

실제 Gemini·식약처 API를 사용하려면 다음과 같이 설정한다.

```dotenv
PROVIDER_MODE=remote
AI_PROVIDER_MODE=remote
LLM_PROVIDER=gemini
GEMINI_API_KEY=발급받은_키
DATA_GO_KR_SERVICE_KEY=공공데이터_Decoding_키
```

모델은 `.env.example`의 `GEMINI_OCR_MODEL`, `GEMINI_CHAT_MODEL`을 사용한다.
API 키는 AI 컨테이너에만 전달되며 Flutter 빌드에 포함되지 않는다.

키 입력 전 서버 연결과 앱 흐름을 확인하려면 `AI_PROVIDER_MODE=mock`으로 바꾼다.
이때도 앱 → Backend → AI는 실제 HTTP로 연결되고 DB에 기록이 저장된다.
OCR·DUR·대화·감정 분석 응답은 가상 데이터이므로 외부 API 품질 검증은 아니다.
Gemini로 전환할 때는 `AI_PROVIDER_MODE=remote`로 복구하고 컨테이너를 다시 실행한다.

## 4. Backend·AI·DB 실행

Docker를 실행한 상태에서 Backend 저장소 루트로 이동한다.

```sh
cd daehwa-donghaeng
docker compose -f compose.yaml -f compose.integration.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.integration.yaml ps
```

PC 브라우저에서 `http://localhost:8090/docs`가 열리는지 확인한다.
문제가 있으면 아래 명령으로 로그를 확인한다.

```sh
docker compose -f compose.yaml -f compose.integration.yaml logs --tail=100 backend ai
```

Docker 안에 Python과 PostgreSQL이 포함되므로 이 방법에는 PC에 별도 Python·DB
설치가 필요 없다. 미니 PC용 `scripts/setup_local.sh`는 Ubuntu 24.04 전용이며
Windows/macOS에서 이 순서를 따를 때는 실행하지 않는다.

## 5. Android 앱 실행

Android Studio에서 가상 휴대폰을 실행한 뒤 별도 터미널에서:

```sh
cd daehwa-donghaeng-frontend/client-repo/app
flutter pub get
flutter devices
flutter run -d emulator-5554 --dart-define=API_BASE_URL=http://10.0.2.2:8090/api/v1
```

`emulator-5554`는 예시다. `flutter devices`에 표시되는 Android 기기 ID로 바꾼다.
Android Studio에서 프로젝트를 열 때는 Flutter 프로젝트인 `client-repo/app`을 연다.

`10.0.2.2`는 Android 에뮬레이터에서 호스트 PC를 가리키는 주소다.
따라서 이 설정은 같은 PC에서 실행한 Docker 백엔드에 연결된다.
[Android 에뮬레이터 네트워크 안내](https://developer.android.com/studio/run/emulator-networking)

웹으로도 확인하려면 같은 앱 폴더에서 다음을 실행한다.

```sh
flutter run -d chrome --web-hostname localhost --web-port 3000 --dart-define=API_BASE_URL=http://localhost:8090/api/v1
```

## 6. 확인과 종료

이름 입력 → 약 사진 또는 직접 입력 → 등록 → DUR → 복약 일정·응답 →
대화 → 선택 동의 후 분석·보호자 리포트 순서로 확인한다.
사진 촬영·음성은 에뮬레이터의 카메라/마이크와 음성 서비스 설정에 따라 달라진다.
실제 약봉투 인식 품질·실제 폰의 절전/재부팅 후 알림 도착은 별도 확인한다.

앱은 `flutter run` 터미널에서 `q`로 종료한다.
서버는 Backend 저장소에서 다음과 같이 종료한다. DB 데이터 볼륨은 유지된다.

```sh
docker compose -f compose.yaml -f compose.integration.yaml down
```

이 브랜치는 개발·시연용이다. 현재 기기 ID 식별 방식과 HTTP 설정을 기준으로 하며
Play 배포용 서명·정식 로그인은 별도 작업이다. 서버 자동 테스트·웹 E2E·Android
APK 빌드는 확인했으나 이 호스트에는 Docker 엔진과 KVM 가속이 없어 Docker 전체
기동과 Android 에뮬레이터 E2E의 성공을 주장하지 않는다.
