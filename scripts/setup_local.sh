#!/usr/bin/env bash
# Ubuntu 24.04 x86_64 local development; no system packages or services modified.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ai_root="$repo_root/../daehwa-donghaeng-frontend/client-repo/ai"
command -v uv >/dev/null || { echo 'uv가 필요합니다: https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
uv python install 3.13
uv sync --project "$repo_root/apps/backend" --python 3.13 --extra dev
uv sync --project "$ai_root" --python 3.13 --extra dev
tool_root="$repo_root/.local/tools/postgres"
if [[ ! -x "$tool_root/usr/lib/postgresql/16/bin/pg_ctl" ]]; then
  mkdir -p "$repo_root/.local/downloads" "$tool_root"
  (
    cd "$repo_root/.local/downloads"
    apt-get download postgresql-16 postgresql-client-16 libpq5
    for archive in ./*.deb; do dpkg-deb -x "$archive" "$tool_root"; done
  )
fi
if [[ ! -f "$repo_root/.env" ]]; then cp "$repo_root/.env.example" "$repo_root/.env"; chmod 600 "$repo_root/.env"; fi
echo '준비 완료. .env의 두 API 키를 입력한 뒤 ./scripts/start_local.sh를 실행하세요.'
