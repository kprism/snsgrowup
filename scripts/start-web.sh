#!/usr/bin/env sh
set -eu

echo "[SNSGROWUP] Applying database migrations..."
python manage.py migrate --noinput

echo "[SNSGROWUP] Running Django system checks..."
python manage.py check

echo "[SNSGROWUP] Starting development server on 0.0.0.0:8000..."
exec python manage.py runserver 0.0.0.0:8000
