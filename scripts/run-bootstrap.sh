#!/usr/bin/env bash
set -euo pipefail

TMP_SCRIPT="$(mktemp)"
cp scripts/bootstrap.sh "$TMP_SCRIPT"

python - "$TMP_SCRIPT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text().splitlines()
fixed = []
for line in lines:
    if line.strip().startswith('s = s.replace("SECRET_KEY ='):
        fixed.append("secret_line = next(line for line in s.splitlines() if line.startswith('SECRET_KEY = '))")
        fixed.append("s = s.replace(secret_line, \"SECRET_KEY = env('SECRET_KEY', default='dev-only-change-before-production')\")")
    else:
        fixed.append(line)
path.write_text("\n".join(fixed) + "\n")
PY

bash "$TMP_SCRIPT"
rm -f "$TMP_SCRIPT"
