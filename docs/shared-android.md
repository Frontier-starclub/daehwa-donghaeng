# 공용 서버와 Android 앱으로 팀 테스트

미니 PC 한 곳에서 Backend·AI·PostgreSQL을 실행하고, 팀원은 같은 서버에 연결되는
테스트 APK를 Android 휴대폰에 설치한다. 팀원이 Docker·Flutter·Android Studio나
Gemini·식약처 API 키를 준비할 필요는 없다.

## 팀원 설치

1. 서버 관리자가 전달한 **설치 링크**를 Android 휴대폰에서 연다.
2. `Android 앱 다운로드`를 누르고 내려받은 APK를 설치한다.
3. Android가 요청하면 해당 브라우저의 앱 설치를 허용한다.
4. 앱에서 이름을 입력한다. 서버 주소와 팀 접근 설정은 APK에 포함되어 있다.
5. 약 등록·DUR·복약 일정·대화를 확인한다. 알림·마이크 권한은 앱에서 허용한다.

앱 변경 후 같은 링크에서 최신 APK를 받아 업데이트한다. 현재 APK는 테스트용
debug 서명으로 release 빌드한 파일이며 Play 배포용이 아니다. 다른 PC에서 다른
키로 서명한 기존 APK가 설치되어 있으면 업데이트가 거절될 수 있다. 기존 앱을
삭제하면 기기 식별자가 바뀌므로 서버의 이전 테스트 기록과 연결되지 않는다.

휴대폰 없이 PC에서 확인할 때는 Android 에뮬레이터에 같은 APK를 설치한다.
카메라·한국어 음성·절전/재부팅 후 알림은 실제 휴대폰에서도 확인한다.

## 서버 구성

```text
Android 앱 → 공용 HTTPS 주소 → 팀 접근 키 확인(127.0.0.1:8099)
                              → Backend(127.0.0.1:8090)
                                ├─ PostgreSQL(127.0.0.1:15432)
                                └─ AI(127.0.0.1:8100) → Gemini·식약처
```

외부에는 접근 제한 진입점만 연결한다. `/api/v1/*`는 APK에 포함된 팀 접근 키가
필요하다. API 문서와 내부 서비스 포트는 이 진입점에서 공개하지 않는다.
`/install/<별도 다운로드 키>`는 APK 설치 링크이고 `/health/live`는 상태만 반환한다.
설치 링크와 APK는 팀 안에서만 공유한다. APK를 가진 사람은 팀 접근 키를 추출할
수 있으므로 이 방식은 정식 개인 인증을 대신하지 않는다. 테스트 데이터로 사용한다.

팀 DB는 `.local/shared/`, 개인 개발 DB는 `.local/development/`로 분리한다.
모든 공급자 API 키는 Backend 저장소의 `.env`에서 AI 프로세스에만 전달한다.
APK에는 Gemini·식약처 API 키를 넣지 않는다.

## 관리자가 처음 준비할 때

Ubuntu 로컬 실행 도구는 [기존 실행 안내](e2e-ready.md)를 따른다.
`.env`에서 Gemini와 식약처 키를 설정한 뒤 공용 HTTPS 주소를 지정한다.

```sh
apps/backend/.venv/bin/python apps/backend/scripts/shared_gateway.py \
  prepare https://YOUR-SERVER.YOUR-TAILNET.ts.net
python3 scripts/shared_services.py install
bash scripts/build_shared_apk.sh
```

`prepare`는 `.local/shared-server/config.json`에 서로 다른 API/다운로드 키를 만들고,
`android-defines.json`에는 `API_BASE_URL`과 `TEST_ACCESS_TOKEN`만 기록한다.
다시 실행해도 기존 키는 보존한다. 이 디렉터리는 Git에서 제외되며 비공개다.
`build_shared_apk.sh`는 완성된 APK만 원자적으로 교체하므로 다운로드 중인 파일에
빌드 결과를 덮어쓰지 않는다. Android SDK·JDK가 PATH에 없으면 `ANDROID_HOME`,
`JAVA_HOME`을 설정하고, 필요하면 `FLUTTER_BIN`, `GRADLE_USER_HOME`을 지정한다.

기존 Tailscale 로그인과 HTTPS/Funnel 활성화가 완료된 서버에서, **팀 테스트
진입점을 인터넷에 공개하기로 결정한 뒤** 다음을 실행한다.

```sh
tailscale funnel --bg --yes http://127.0.0.1:8099
```

Tailscale이 계정 설정 링크를 출력하면 관리자가 열어 HTTPS/Funnel을 활성화한다.
Funnel은 외부 공개용이므로 팀원 휴대폰에 Tailscale 설치가 필요 없다.
일반 `tailscale serve`는 같은 기능이 아니며 Tailscale 네트워크 안에서만 접근한다.
[Tailscale Funnel 공식 안내](https://tailscale.com/docs/features/tailscale-funnel)

공개 연결을 활성화한 뒤 외부 HTTPS에서 익명 API 요청이 401인지, 유효한 팀 키로
사용자 등록·조회가 성공하는지, 설치 링크에서 APK 다운로드가 되는지 확인한다.
로컬 확인만으로 외부 접속 완료라고 판단하지 않는다.

## 운영 명령

```sh
# API 주소와 비공개 설치 링크 출력 — 출력된 설치 링크는 공개 Git에 올리지 않는다.
apps/backend/.venv/bin/python apps/backend/scripts/shared_gateway.py links
python3 scripts/shared_services.py status
python3 scripts/shared_services.py restart
# 서버 종료; 데이터는 유지
python3 scripts/shared_services.py stop
# 이 서비스의 외부 공개만 해제
tailscale funnel --https=443 off
```

서비스는 `daehwa-shared.service`와 `daehwa-gateway.service`라는 systemd 사용자
서비스다. `loginctl show-user "$USER" -p Linger`가 `Linger=yes`이면 로그아웃 후와
재부팅 후에도 실행된다. 로그는 `journalctl --user -u daehwa-gateway.service`와
`.local/shared/`에서 확인한다. 요청 접근 로그는 비공개 설치 경로를 남기지 않는다.

공용 주소가 바뀌면 `prepare`와 APK 빌드를 다시 실행해 업데이트한다. 팀 접근 키를
교체할 때도 새 APK 배포가 필요하다. 기존 DB 디렉터리는 삭제하지 않는다.

## 현재 확인 범위

- 2026-09-27: 실제 키를 사용한 Gemini 대화와 식약처 품목·병용금기·노인주의·효능군중복 조회 성공.
- 접근 제한·헤더 전달·사진 업로드 전달·APK 다운로드 경로 테스트 통과.
- Backend 109 passed, Flutter 42 passed / 조건부 HTTP 테스트 1 skipped, 정적 분석 통과.
- 공용 주소·팀 접근 설정을 포함한 release APK 빌드와 로컬 설치 링크 다운로드/해시 검증 완료.
  ARM32·ARM64·x86_64를 포함하며 최소 Android 7.0(API 24)이 필요하다.
- 실제 Android 설치·카메라·음성·알림 도착은 팀원 기기에서 검증해야 한다.
- 서버 공개 여부와 최신 APK 빌드 결과는 배포 시점의 상태를 별도로 확인한다.
