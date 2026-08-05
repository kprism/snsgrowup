from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings


class InstagramOAuthError(RuntimeError):
    pass


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise InstagramOAuthError(f"Instagram 연결 응답 오류: {body[:500]}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise InstagramOAuthError(f"Instagram 연결 실패: {exc}") from exc


def fetch_professional_accounts(*, pages: list[dict]) -> list[dict]:
    """Return Instagram professional accounts linked to managed Facebook pages."""
    accounts: list[dict] = []
    for page in pages:
        page_id = str(page.get("id", "")).strip()
        page_token = str(page.get("access_token", "")).strip()
        if not page_id or not page_token:
            continue

        params = {
            "fields": (
                "instagram_business_account{"
                "id,username,name,profile_picture_url,followers_count,media_count"
                "}"
            ),
            "access_token": page_token,
        }
        payload = _get_json(
            f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/{page_id}?{urlencode(params)}"
        )
        instagram = payload.get("instagram_business_account") or {}
        instagram_id = str(instagram.get("id", "")).strip()
        if not instagram_id:
            continue

        username = str(instagram.get("username", "")).strip()
        accounts.append(
            {
                "id": instagram_id,
                "username": username,
                "name": str(instagram.get("name", "")).strip() or username or "Instagram 계정",
                "profile_picture_url": str(instagram.get("profile_picture_url", "")),
                "followers_count": instagram.get("followers_count"),
                "media_count": instagram.get("media_count"),
                "profile_url": f"https://www.instagram.com/{username}/" if username else "https://www.instagram.com/",
                "page_id": page_id,
                "page_name": str(page.get("name", "Facebook 페이지")),
                "access_token": page_token,
            }
        )
    return accounts
