#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
flutter_bin="${FLUTTER_BIN:-$repo_root/.local/tools/flutter/bin/flutter}"
if [[ ! -x "$flutter_bin" ]]; then
  flutter_bin="$(command -v flutter || true)"
fi
if [[ -z "$flutter_bin" ]]; then echo 'Flutter SDK를 설치하거나 FLUTTER_BIN을 지정해주세요.'; exit 1; fi
export PUB_CACHE="${PUB_CACHE:-$repo_root/.local/tools/pub-cache}"
export FLUTTER_SUPPRESS_ANALYTICS=true
export DART_SUPPRESS_ANALYTICS=true
cd "$repo_root/../daehwa-donghaeng-frontend/client-repo/app"
exec "$flutter_bin" run -d web-server --web-hostname 127.0.0.1 --web-port 3000 \
  --dart-define=API_BASE_URL=http://localhost:8090/api/v1 "$@"
