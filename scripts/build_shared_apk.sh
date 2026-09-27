#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
state="$repo_root/.local/shared-server"
if [[ ! -f "$state/android-defines.json" ]]; then
  echo '먼저 shared_gateway.py prepare 명령으로 HTTPS 주소를 설정해주세요.'
  exit 1
fi
flutter_bin="${FLUTTER_BIN:-$repo_root/.local/tools/flutter/bin/flutter}"
if [[ ! -x "$flutter_bin" ]]; then flutter_bin="$(command -v flutter || true)"; fi
if [[ -z "$flutter_bin" ]]; then echo 'Flutter SDK 또는 FLUTTER_BIN이 필요합니다.'; exit 1; fi
export PUB_CACHE="${PUB_CACHE:-$repo_root/.local/tools/pub-cache}"
export FLUTTER_SUPPRESS_ANALYTICS=true
export DART_SUPPRESS_ANALYTICS=true
cd "$repo_root/../daehwa-donghaeng-frontend/client-repo/app"
"$flutter_bin" build apk --release --dart-define-from-file="$state/android-defines.json" "$@"
cp build/app/outputs/flutter-apk/app-release.apk "$state/daehwa-donghaeng-test.apk.next"
chmod 600 "$state/daehwa-donghaeng-test.apk.next"
mv "$state/daehwa-donghaeng-test.apk.next" "$state/daehwa-donghaeng-test.apk"
sha256sum "$state/daehwa-donghaeng-test.apk" > "$state/apk.sha256"
echo '공용 서버 연결용 APK: .local/shared-server/daehwa-donghaeng-test.apk'
