from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import feedparser
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from contents.models import ContentItem
from .models import PressProfile


@dataclass
class RSSCollectResult:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    feed_title: str = ""


def _entry_value(entry: Any, key: str, default: str = "") -> str:
    value = entry.get(key, default)
    return str(value or default).strip()


def _published_at(entry: Any):
    """Return an aware datetime without depending on removed Django timezone.utc."""
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except (TypeError, ValueError, OverflowError):
                continue

    for key in ("published", "updated"):
        raw = _entry_value(entry, key)
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _body(entry: Any) -> str:
    candidates = []
    for item in entry.get("content", []) or []:
        candidates.append(item.get("value", ""))
    candidates.extend([entry.get("summary", ""), entry.get("description", "")])
    for raw in candidates:
        text = strip_tags(unescape(str(raw or ""))).strip()
        if text:
            return text
    return ""


def _image_url(entry: Any) -> str:
    media_content = entry.get("media_content", []) or []
    for media in media_content:
        url = str(media.get("url", "")).strip()
        if url:
            return url

    media_thumbnail = entry.get("media_thumbnail", []) or []
    for media in media_thumbnail:
        url = str(media.get("url", "")).strip()
        if url:
            return url

    for enclosure in entry.get("enclosures", []) or []:
        url = str(enclosure.get("href") or enclosure.get("url") or "").strip()
        media_type = str(enclosure.get("type", ""))
        if url and (not media_type or media_type.startswith("image/")):
            return url
    return ""


def inspect_feed(profile: PressProfile) -> dict[str, Any]:
    feed = feedparser.parse(profile.rss_url)
    if getattr(feed, "bozo", False) and not feed.entries:
        error = getattr(feed, "bozo_exception", None)
        raise ValueError(f"RSS를 읽을 수 없습니다: {error or '형식 오류'}")
    return {
        "title": str(feed.feed.get("title", "")).strip(),
        "entry_count": len(feed.entries),
        "version": getattr(feed, "version", "") or "unknown",
    }


@transaction.atomic
def collect_feed(profile: PressProfile, *, limit: int = 100) -> RSSCollectResult:
    feed = feedparser.parse(profile.rss_url)
    if getattr(feed, "bozo", False) and not feed.entries:
        error = getattr(feed, "bozo_exception", None)
        profile.rss_verified = False
        profile.collection_status = "failed"
        profile.save(update_fields=["rss_verified", "collection_status"])
        raise ValueError(f"RSS 수집 실패: {error or '형식 오류'}")

    result = RSSCollectResult(feed_title=str(feed.feed.get("title", "")).strip())

    for entry in list(feed.entries)[:limit]:
        try:
            title = _entry_value(entry, "title")
            source_url = _entry_value(entry, "link")
            guid = _entry_value(entry, "id") or source_url
            if not title or not guid:
                result.failed += 1
                continue

            defaults = {
                "source_type": ContentItem.SourceType.RSS,
                "title": title[:300],
                "body": _body(entry),
                "source_url": source_url,
                "published_at": _published_at(entry),
            }
            item, created = ContentItem.objects.get_or_create(
                owner=profile.user,
                external_guid=guid[:500],
                defaults=defaults,
            )
            if created:
                # 원격 이미지는 다음 발행 변환 단계에서 별도 필드로 정식 관리한다.
                image_url = _image_url(entry)
                if image_url and not item.body:
                    item.body = image_url
                    item.save(update_fields=["body"])
                result.created += 1
            else:
                result.skipped += 1
        except Exception:
            # 한 기사 데이터가 깨져도 전체 RSS 수집을 중단하지 않는다.
            result.failed += 1

    profile.rss_verified = True
    profile.collection_status = "success"
    profile.last_collected_at = timezone.now()
    profile.save(update_fields=["rss_verified", "collection_status", "last_collected_at"])
    return result
