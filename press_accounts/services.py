from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

import feedparser
from PIL import Image
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from contents.models import ContentItem
from .models import PressProfile


ProgressCallback = Callable[[int, int, str], None]


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
    for media in entry.get("media_content", []) or []:
        url = str(media.get("url", "")).strip()
        if url:
            return url

    for media in entry.get("media_thumbnail", []) or []:
        url = str(media.get("url", "")).strip()
        if url:
            return url

    for enclosure in entry.get("enclosures", []) or []:
        url = str(enclosure.get("href") or enclosure.get("url") or "").strip()
        media_type = str(enclosure.get("type", ""))
        if url and (not media_type or media_type.startswith("image/")):
            return url
    return ""


def _save_webp_image(item: ContentItem, image_url: str) -> bool:
    if not image_url or item.representative_image:
        return False

    try:
        request = Request(image_url, headers={"User-Agent": "SNSGROWUP/1.0"})
        with urlopen(request, timeout=12) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if not raw or len(raw) > 8 * 1024 * 1024:
            return False

        with Image.open(BytesIO(raw)) as source:
            image = source.convert("RGB")
            image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=6)

        stem = Path(item.external_guid or str(item.pk)).stem[:60] or str(item.pk)
        safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stem)
        item.representative_image.save(
            f"rss-{item.pk}-{safe_stem}.webp",
            ContentFile(output.getvalue()),
            save=True,
        )
        return True
    except Exception:
        return False


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
def collect_feed(
    profile: PressProfile,
    *,
    limit: int = 100,
    progress_callback: ProgressCallback | None = None,
) -> RSSCollectResult:
    feed = feedparser.parse(profile.rss_url)
    if getattr(feed, "bozo", False) and not feed.entries:
        error = getattr(feed, "bozo_exception", None)
        profile.rss_verified = False
        profile.collection_status = "failed"
        profile.save(update_fields=["rss_verified", "collection_status"])
        raise ValueError(f"RSS 수집 실패: {error or '형식 오류'}")

    entries = list(feed.entries)[:limit]
    total = len(entries)
    result = RSSCollectResult(feed_title=str(feed.feed.get("title", "")).strip())

    if progress_callback:
        progress_callback(0, total, "RSS 목록을 확인하고 있습니다.")

    for index, entry in enumerate(entries, start=1):
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

            image_url = _image_url(entry)
            if image_url and not item.representative_image:
                _save_webp_image(item, image_url)

            if created:
                result.created += 1
            else:
                result.skipped += 1
        except Exception:
            result.failed += 1
        finally:
            if progress_callback:
                progress_callback(index, total, f"기사와 이미지를 처리하고 있습니다. {index}/{total}")

    profile.rss_verified = True
    profile.collection_status = "success"
    profile.last_collected_at = timezone.now()
    profile.save(update_fields=["rss_verified", "collection_status", "last_collected_at"])
    return result
