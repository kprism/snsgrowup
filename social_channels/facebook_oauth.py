from __future__ import annotations

import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.utils import timezone


class FacebookOAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET)


def authorization_url(*, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(settings.FACEBOOK_OAUTH_SCOPES),
    }
    return f"https://www.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise FacebookOAuthError(f"Facebook 응답 오류: {body[:300]}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FacebookOAuthError(f"Facebook 연결 실패: {exc}") from exc


def exchange_code(*, code: str, redirect_uri: str) -> dict:
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "client_secret": settings.FACEBOOK_APP_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    return _get_json(
        f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/oauth/access_token?{urlencode(params)}"
    )


def fetch_profile(*, access_token: str) -> dict:
    params = {"fields": "id,name", "access_token": access_token}
    return _get_json(
        f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/me?{urlencode(params)}"
    )


def expiry_datetime(token_data: dict):
    expires_in = token_data.get("expires_in")
    if not expires_in:
        return None
    try:
        return timezone.now() + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None
