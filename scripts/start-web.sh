#!/usr/bin/env sh
set -eu

MAX_ATTEMPTS="${DB_WAIT_ATTEMPTS:-30}"
ATTEMPT=1

echo "[SNSGROWUP] Waiting for PostgreSQL..."
while ! python - <<'PY'
import os
import socket

host = os.getenv("POSTGRES_HOST", "db")
port = int(os.getenv("POSTGRES_PORT", "5432"))
with socket.create_connection((host, port), timeout=2):
    pass
PY
do
  if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
    echo "[SNSGROWUP] PostgreSQL did not become available after ${MAX_ATTEMPTS} attempts."
    exit 1
  fi
  echo "[SNSGROWUP] PostgreSQL not ready (${ATTEMPT}/${MAX_ATTEMPTS}); retrying in 2 seconds..."
  ATTEMPT=$((ATTEMPT + 1))
  sleep 2
done

echo "[SNSGROWUP] PostgreSQL is available."
echo "[SNSGROWUP] Applying database migrations..."
python manage.py migrate --noinput

echo "[SNSGROWUP] Running Django system checks..."
python manage.py check

echo "[SNSGROWUP] Starting development server on 0.0.0.0:8000..."
exec python manage.py runserver 0.0.0.0:8000
