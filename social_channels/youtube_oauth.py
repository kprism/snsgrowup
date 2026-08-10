from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone


AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeOAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.YOUTUBE_CLIENT_ID and settings.YOUTUBE_CLIENT_SECRET)


def authorization_url(*, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": settings.YOUTUBE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.YOUTUBE_OAUTH_SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def exchange_code(*, code: str, redirect_uri: str) -> dict:
    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    data = _json_response(response, "YouTube OAuth 토큰 발급")
    if not data.get("access_token"):
        raise YouTubeOAuthError("Google OAuth 응답에 access_token이 없습니다.")
    return data


def refresh_access_token(*, refresh_token: str) -> dict:
    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "refresh_token": refresh_token,
            "client_id": settings.YOUTUBE_CLIENT_ID,
            "client_secret": settings.YOUTUBE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    data = _json_response(response, "YouTube OAuth 토큰 갱신")
    if not data.get("access_token"):
        raise YouTubeOAuthError("Google OAuth 갱신 응답에 access_token이 없습니다.")
    return data


def fetch_my_channel(*, access_token: str) -> dict:
    response = requests.get(
        f"{YOUTUBE_API_BASE}/channels",
        params={"part": "snippet,statistics", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    data = _json_response(response, "YouTube 채널 조회")
    items = data.get("items") or []
    if not items:
        raise YouTubeOAuthError(
            "이 Google 계정에서 연결 가능한 YouTube 채널을 찾지 못했습니다. "
            "YouTube 채널이 생성되어 있는 계정인지 확인해 주세요."
        )
    return items[0]


def expiry_datetime(token_data: dict):
    expires_in = token_data.get("expires_in")
    if not expires_in:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return timezone.now() + timedelta(seconds=max(seconds - 60, 0))


def granted_scopes(token_data: dict) -> list[str]:
    raw = token_data.get("scope") or ""
    if isinstance(raw, str):
        scopes = [scope for scope in raw.split() if scope]
    else:
        scopes = []
    return scopes or list(settings.YOUTUBE_OAUTH_SCOPES)


def _json_response(response, label: str) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise YouTubeOAuthError(f"{label} 응답을 해석할 수 없습니다. HTTP {response.status_code}") from exc

    if response.ok:
        return data

    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or str(error)
    else:
        message = data.get("error_description") or error or response.text
    raise YouTubeOAuthError(f"{label} 실패: {message}")
