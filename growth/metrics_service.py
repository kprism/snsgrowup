from __future__ import annotations

import json
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.utils import timezone

from .models import ChannelMetricSnapshot, GrowthAction


class MetricCollectionError(RuntimeError):
    pass


def _get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MetricCollectionError(body[:500]) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MetricCollectionError(str(exc)) from exc


def _facebook_metrics(account) -> tuple[int | None, int | None, int | None]:
    if not account.external_account_id or not account.access_token:
        raise MetricCollectionError("Facebook 페이지 연결 정보가 부족합니다.")

    fields = "followers_count,fan_count,posts.limit(50){reactions.limit(0).summary(true),comments.limit(0).summary(true)}"
    params = {"fields": fields, "access_token": account.access_token}
    url = f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/{account.external_account_id}?{urlencode(params)}"
    payload = _get_json(url)

    followers = payload.get("followers_count")
    if followers is None:
        followers = payload.get("fan_count")

    reactions = 0
    comments = 0
    posts = ((payload.get("posts") or {}).get("data") or [])
    for post in posts:
        reactions += int((((post.get("reactions") or {}).get("summary") or {}).get("total_count") or 0))
        comments += int((((post.get("comments") or {}).get("summary") or {}).get("total_count") or 0))
    return int(followers) if followers is not None else None, reactions, comments


def collect_account_snapshot(account, *, force: bool = False) -> ChannelMetricSnapshot:
    recent = account.metric_snapshots.first()
    if recent and not force and recent.collected_at >= timezone.now() - timedelta(minutes=10):
        return recent

    completed_actions = GrowthAction.objects.filter(
        owner=account.user,
        platform=account.platform.code,
        status=GrowthAction.Status.COMPLETED,
    ).count()

    try:
        if account.platform.code != "facebook":
            raise MetricCollectionError("현재 실제 지표 자동수집은 Facebook부터 지원합니다.")
        followers, reactions, comments = _facebook_metrics(account)
        return ChannelMetricSnapshot.objects.create(
            owner=account.user,
            social_account=account,
            platform=account.platform.code,
            followers_count=followers,
            reactions_count=reactions,
            comments_count=comments,
            completed_actions_count=completed_actions,
            collection_ok=True,
        )
    except Exception as exc:
        return ChannelMetricSnapshot.objects.create(
            owner=account.user,
            social_account=account,
            platform=account.platform.code,
            completed_actions_count=completed_actions,
            collection_ok=False,
            error_message=str(exc)[:500],
        )


def metric_comparison(account) -> dict:
    latest = collect_account_snapshot(account)
    yesterday = timezone.localdate() - timedelta(days=1)
    previous = account.metric_snapshots.filter(
        collection_ok=True,
        collected_at__date__lte=yesterday,
    ).order_by("-collected_at").first()

    def item(label: str, field: str):
        current = getattr(latest, field, None) if latest and latest.collection_ok else None
        before = getattr(previous, field, None) if previous else None
        delta = current - before if current is not None and before is not None else None
        return {"label": label, "current": current, "previous": before, "delta": delta}

    return {
        "latest": latest,
        "previous": previous,
        "items": [
            item("팔로워", "followers_count"),
            item("공감", "reactions_count"),
            item("댓글", "comments_count"),
            item("실행 작업", "completed_actions_count"),
        ],
    }
