#!/usr/bin/env sh
set -eu

BASE_URL="${SNSGROWUP_VERIFY_URL:-http://127.0.0.1:8000}"
MAX_ATTEMPTS="${SNSGROWUP_VERIFY_ATTEMPTS:-30}"

printf '\n[SNSGROWUP] 1/5 Container status\n'
docker compose ps

printf '\n[SNSGROWUP] 2/5 Django system check\n'
docker compose exec -T web python manage.py check

printf '\n[SNSGROWUP] 3/5 Critical URL reverse check\n'
docker compose exec -T web python manage.py shell -c "from django.urls import reverse; names=['home','growth:action_center','growth:generate_actions','publishing:batch_list','publishing:automation_settings','contents:content_list']; [(print(name, reverse(name))) for name in names]"

printf '\n[SNSGROWUP] 4/5 Web readiness check\n'
ATTEMPT=1
while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
  STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL/" || true)"
  case "$STATUS" in
    200|301|302)
      echo "Web ready: HTTP $STATUS"
      break
      ;;
  esac
  if [ "$ATTEMPT" -eq "$MAX_ATTEMPTS" ]; then
    echo "Web did not become ready. Recent logs:"
    docker compose logs --tail=120 web
    exit 1
  fi
  echo "Waiting for web (${ATTEMPT}/${MAX_ATTEMPTS}), HTTP ${STATUS:-none}..."
  ATTEMPT=$((ATTEMPT + 1))
  sleep 2
done

printf '\n[SNSGROWUP] 5/5 Critical route response check\n'
for PATHNAME in /growth/ /publishing/ /settings/automation/ /contents/; do
  STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_URL$PATHNAME" || true)"
  case "$STATUS" in
    200|301|302)
      echo "$PATHNAME -> HTTP $STATUS"
      ;;
    *)
      echo "$PATHNAME failed with HTTP ${STATUS:-none}"
      docker compose logs --tail=120 web
      exit 1
      ;;
  esac
done

echo '\n[SNSGROWUP] Deployment verification passed.'
