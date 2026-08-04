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
    return bool(
        settings.FACEBOOK_APP_ID
        and settings.FACEBOOK_APP_SECRET
        and settings.FACEBOOK_LOGIN_CONFIG_ID
    )


def missing_configuration() -> list[str]:
    missing = []
    if not settings.FACEBOOK_APP_ID:
        missing.append("META_APP_ID 또는 FACEBOOK_APP_ID")
    if not settings.FACEBOOK_APP_SECRET:
        missing.append("META_APP_SECRET 또는 FACEBOOK_APP_SECRET")
    if not settings.FACEBOOK_LOGIN_CONFIG_ID:
        missing.append("META_LOGIN_CONFIG_ID 또는 FACEBOOK_LOGIN_CONFIG_ID")
    return missing


def authorization_url(*, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }

    # Facebook Login for Business에서는 권한을 scope 쿼리로 직접 전달하지 않고,
    # Meta 개발자센터의 구성(Configuration)에 저장한 뒤 config_id로 참조한다.
    if settings.FACEBOOK_LOGIN_CONFIG_ID:
        params.update(
            {
                "config_id": settings.FACEBOOK_LOGIN_CONFIG_ID,
                "override_default_response_type": "true",
            }
        )
    elif settings.FACEBOOK_OAUTH_SCOPES:
        params["scope"] = ",".join(settings.FACEBOOK_OAUTH_SCOPES)

    return f"https://www.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise FacebookOAuthError(f"Facebook 응답 오류: {body[:500]}") from exc
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


def fetch_permissions(*, access_token: str) -> list[str]:
    params = {"access_token": access_token}
    payload = _get_json(
        f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/me/permissions?{urlencode(params)}"
    )
    return [
        str(item.get("permission", ""))
        for item in payload.get("data", [])
        if item.get("status") == "granted" and item.get("permission")
    ]


def fetch_managed_pages(*, access_token: str) -> list[dict]:
    params = {
        "fields": "id,name,category,access_token,tasks,picture{url},link",
        "access_token": access_token,
        "limit": 100,
    }
    payload = _get_json(
        f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/me/accounts?{urlencode(params)}"
    )
    pages = []
    for item in payload.get("data", []) or []:
        page_id = str(item.get("id", "")).strip()
        page_token = str(item.get("access_token", "")).strip()
        if not page_id or not page_token:
            continue
        picture = item.get("picture") or {}
        picture_data = picture.get("data") or {}
        pages.append(
            {
                "id": page_id,
                "name": str(item.get("name", "Facebook 페이지")),
                "category": str(item.get("category", "")),
                "access_token": page_token,
                "tasks": item.get("tasks") or [],
                "picture_url": str(picture_data.get("url", "")),
                "link": str(item.get("link", "")),
            }
        )
    return pages


def expiry_datetime(token_data: dict):
    expires_in = token_data.get("expires_in")
    if not expires_in:
        return None
    try:
        return timezone.now() + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None
