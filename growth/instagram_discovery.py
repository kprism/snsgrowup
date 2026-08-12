from __future__ import annotations

import re

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from social_channels.models import SocialAccount

from .models import GrowthAction


_GENERIC = {
    "관련", "지역", "정보", "게시물", "릴스", "reels", "instagram", "인스타그램",
    "오늘", "미션", "콘텐츠", "계정", "후보", "상위",
}


def _hashtag_candidates(keyword: str) -> list[str]:
    tokens = [
        token.strip("#_-")
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", keyword or "")
    ]
    candidates: list[str] = []
    for token in tokens:
        if not token or token.lower() in _GENERIC:
            continue
        if token not in candidates:
            candidates.append(token)
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", keyword or "")
    if compact and compact not in candidates and len(compact) <= 40:
        candidates.append(compact)
    return candidates[:6]


def _graph_get(path: str, *, params: dict) -> dict:
    version = settings.FACEBOOK_GRAPH_VERSION
    response = requests.get(
        f"https://graph.facebook.com/{version}/{path.lstrip('/')}",
        params=params,
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"Instagram API 응답을 해석하지 못했습니다. HTTP {response.status_code}") from exc
    if not response.ok or payload.get("error"):
        error = payload.get("error") or {}
        message = error.get("message") or f"Instagram API 오류 HTTP {response.status_code}"
        raise ValueError(message)
    return payload


def _recent_media(*, hashtag_id: str, ig_user_id: str, token: str) -> dict:
    """Fetch hashtag media using only fields supported by the hashtag edge.

    The set of fields exposed by Instagram hashtag discovery is narrower than
    the fields exposed for media owned by the authenticated account. In
    particular, media_product_type, username and thumbnail_url can trigger
    Graph API error #100 on hashtag recent_media. Try progressively smaller
    field sets so API-version differences do not break discovery completely.
    """
    base = {
        "user_id": ig_user_id,
        "limit": 30,
        "access_token": token,
    }
    field_sets = [
        "id,caption,media_type,media_url,permalink,timestamp",
        "id,caption,media_type,permalink,timestamp",
        "id,caption,media_type,permalink",
        "id,media_type,permalink",
    ]
    last_error: Exception | None = None
    for fields in field_sets:
        try:
            return _graph_get(
                f"{hashtag_id}/recent_media",
                params={**base, "fields": fields},
            )
        except ValueError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return {"data": []}


def _discover_hashtag_media(*, account: SocialAccount, hashtag: str) -> list[dict]:
    token = (account.access_token or "").strip()
    ig_user_id = (account.external_account_id or "").strip()
    if not token or not ig_user_id:
        raise ValueError("Instagram 연결 정보가 없습니다. SNS 채널에서 Instagram 계정을 다시 연결해 주세요.")

    search = _graph_get(
        "ig_hashtag_search",
        params={"user_id": ig_user_id, "q": hashtag, "access_token": token},
    )
    hashtag_rows = search.get("data") or []
    if not hashtag_rows:
        return []
    hashtag_id = str(hashtag_rows[0].get("id") or "").strip()
    if not hashtag_id:
        return []

    payload = _recent_media(hashtag_id=hashtag_id, ig_user_id=ig_user_id, token=token)
    results = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        media_type = str(row.get("media_type") or "").upper()
        permalink = str(row.get("permalink") or "")

        # Hashtag discovery does not reliably expose media_product_type.
        # Instagram Reel permalinks contain /reel/; VIDEO is also kept as a
        # Reel/video candidate so useful video results are not discarded.
        row["is_reel"] = "/reel/" in permalink.lower() or media_type == "VIDEO"

        # media_url can be rendered directly for image results. Hashtag media
        # does not consistently expose thumbnail_url for third-party videos.
        row["display_image"] = row.get("media_url") if media_type == "IMAGE" else ""
        row["display_account"] = "Instagram 공개 게시물"
        results.append(row)
    return results


@login_required
def instagram_discover(request, pk: int):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user, platform="instagram")
    account = (
        SocialAccount.objects.filter(
            user=request.user,
            is_active=True,
            platform__code="instagram",
        )
        .select_related("platform")
        .first()
    )
    if not account:
        return render(
            request,
            "growth/instagram_discover.html",
            {
                "action": action,
                "account": None,
                "hashtag": "",
                "hashtag_candidates": [],
                "mode": "all",
                "media": [],
                "error": "연결된 Instagram 계정을 찾지 못했습니다.",
            },
        )

    candidates = _hashtag_candidates(action.keyword)
    requested = re.sub(r"[^0-9A-Za-z가-힣]", "", (request.GET.get("q") or "").strip())
    hashtag = requested or (candidates[0] if candidates else "")
    mode = (request.GET.get("mode") or "all").strip().lower()
    if mode not in {"all", "reels", "posts"}:
        mode = "all"

    media: list[dict] = []
    error = ""
    if hashtag:
        try:
            media = _discover_hashtag_media(account=account, hashtag=hashtag)
        except Exception as exc:
            error = str(exc)
    else:
        error = "검색할 Instagram 해시태그 후보를 만들지 못했습니다. 미션 검색키워드를 더 구체적으로 생성해 주세요."

    if mode == "reels":
        media = [row for row in media if row.get("is_reel")]
    elif mode == "posts":
        media = [row for row in media if not row.get("is_reel")]

    return render(
        request,
        "growth/instagram_discover.html",
        {
            "action": action,
            "account": account,
            "hashtag": hashtag,
            "hashtag_candidates": candidates,
            "mode": mode,
            "media": media[:20],
            "error": error,
        },
    )
