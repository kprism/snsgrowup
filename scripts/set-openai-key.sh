#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
fi

printf 'OpenAI API key를 입력하세요. 입력 내용은 화면에 표시되지 않습니다.\n'
IFS= read -r -s -p 'OPENAI_API_KEY: ' OPENAI_KEY
printf '\n'

if [[ -z "$OPENAI_KEY" ]]; then
  printf '오류: API key가 비어 있습니다.\n' >&2
  exit 1
fi

python - "$ENV_FILE" "$OPENAI_KEY" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
secret = sys.argv[2]
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
updated = []
found = False
for line in lines:
    if line.startswith("OPENAI_API_KEY="):
        updated.append(f"OPENAI_API_KEY={secret}")
        found = True
    else:
        updated.append(line)
if not found:
    if updated and updated[-1] != "":
        updated.append("")
    updated.append(f"OPENAI_API_KEY={secret}")
env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY

unset OPENAI_KEY
chmod 600 "$ENV_FILE"

docker compose up -d --force-recreate web worker >/dev/null

WEB_STATE=$(docker compose ps --format json web 2>/dev/null || true)
WORKER_STATE=$(docker compose ps --format json worker 2>/dev/null || true)

printf '완료: OPENAI_API_KEY를 .env에 안전하게 저장하고 web/worker에 반영했습니다.\n'
printf '키 값은 출력하지 않았으며 .env는 Git 추적 대상이 아닙니다.\n'
