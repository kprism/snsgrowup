from __future__ import annotations

import re
import time
from collections import Counter
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from shorts.services import ShortsGenerationError, generate_news_short
from social_channels import youtube_oauth

from .models import AutomationSetting, PublishQueue, PublishingTask

RETRY_DELAYS = [300, 900, 1800, 3600, 7200]


def _final_message(payload: dict) -> str:
    parts = [str(payload.get("message") or "").strip(), str(payload.get("hashtags") or "").strip()]
    return "\n\n".join(part for part in parts if part)


def _facebook_image_file(image_path: Path):
    """Keep local WebP storage, but upload a JPEG byte stream for broad API compatibility."""
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
    output.seek(0)
    return output


def _queue_success(queue_id: int | None):
    if not queue_id:
        return
    PublishQueue.objects.filter(pk=queue_id).update(
        status=PublishQueue.Status.COMPLETED,
        next_retry_at=None,
        last_error="",
        updated_at=timezone.now(),
    )


def _queue_failure(queue_id: int | None, task: PublishingTask, message: str):
    if not queue_id:
        return
    queue = PublishQueue.objects.filter(pk=queue_id).first()
    if not queue:
        return
    setting, _ = AutomationSetting.objects.get_or_create(owner=task.batch.owner)
    if setting.retry_enabled and queue.retry_count < len(RETRY_DELAYS):
        delay = RETRY_DELAYS[queue.retry_count]
        queue.retry_count += 1
        queue.next_retry_at = timezone.now() + timedelta(seconds=delay)
        queue.status = PublishQueue.Status.RETRY
    else:
        queue.status = PublishQueue.Status.FAILED
        queue.next_retry_at = None
    queue.last_error = message[:2000]
    queue.save(update_fields=["retry_count", "next_retry_at", "status", "last_error", "updated_at"])


def _fail_task(task: PublishingTask, queue_id: int | None, message: str, *, connection_required=False):
    task.status = PublishingTask.Status.CONNECTION_REQUIRED if connection_required else PublishingTask.Status.FAILED
    task.error_message = message[:2000]
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    _queue_failure(queue_id, task, task.error_message)
    task.batch.refresh_status()
    return {"ok": False, "message": task.error_message}


def _start_task(task: PublishingTask):
    task.status = PublishingTask.Status.PROCESSING
    task.started_at = timezone.now()
    task.finished_at = None
    task.attempt_count += 1
    task.error_message = ""
    task.save(update_fields=["status", "started_at", "finished_at", "attempt_count", "error_message", "updated_at"])
    task.batch.refresh_status()


def _finish_task(task: PublishingTask, queue_id: int | None, external_id: str, external_url: str = ""):
    task.status = PublishingTask.Status.SUCCESS
    task.external_post_id = external_id
    task.external_post_url = external_url
    task.error_message = ""
    task.finished_at = timezone.now()
    task.save(update_fields=["status", "external_post_id", "external_post_url", "error_message", "finished_at", "updated_at"])
    _queue_success(queue_id)
    task.batch.refresh_status()
    return {"ok": True, "external_post_id": external_id, "external_post_url": external_url}


@shared_task
def dispatch_due_publish_queues(limit: int = 20):
    """예약시각 또는 재시도시각이 지난 Queue를 플랫폼별 Celery 게시 작업으로 넘긴다."""
    now = timezone.now()
    dispatched = []
    with transaction.atomic():
        queues = list(
            PublishQueue.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=PublishQueue.Status.SCHEDULED, scheduled_at__lte=now)
                | Q(status=PublishQueue.Status.RETRY, next_retry_at__lte=now)
            )
            .select_related("task__channel__platform")
            .order_by("scheduled_at", "id")[:limit]
        )
        for queue in queues:
            queue.status = PublishQueue.Status.PROCESSING
            queue.save(update_fields=["status", "updated_at"])
            dispatched.append((queue.task_id, queue.pk, queue.task.channel.platform.code))

    for task_id, queue_id, platform in dispatched:
        if platform == "facebook":
            publish_facebook_task.delay(task_id, queue_id)
        elif platform == "instagram":
            publish_instagram_task.delay(task_id, queue_id)
        elif platform == "youtube":
            publish_youtube_short_task.delay(task_id, queue_id)
        else:
            task = PublishingTask.objects.select_related("batch").get(pk=task_id)
            _fail_task(task, queue_id, f"지원하지 않는 게시 채널입니다: {platform}")
    return {"dispatched": len(dispatched)}


@shared_task(bind=True)
def publish_facebook_task(self, publishing_task_id: int, queue_id: int | None = None):
    task = PublishingTask.objects.select_related(
        "batch", "batch__owner", "content", "channel__platform",
    ).get(pk=publishing_task_id)

    if task.channel.platform.code != "facebook":
        return _fail_task(task, queue_id, "Facebook 작업이 아닙니다.")
    if not task.channel.is_connected or not task.channel.access_token or not task.channel.external_account_id:
        return _fail_task(task, queue_id, "Facebook 페이지 연결 또는 Page Access Token이 필요합니다.", connection_required=True)

    _start_task(task)
    payload = task.payload or {}
    message = _final_message(payload)
    page_id = task.channel.external_account_id
    token = task.channel.access_token
    version = settings.FACEBOOK_GRAPH_VERSION
    graph_root = f"https://graph.facebook.com/{version}/{page_id}"

    try:
        include_image = bool(payload.get("include_image")) and bool(task.content.representative_image)
        include_link = bool(payload.get("include_link")) and bool(payload.get("link"))
        if include_image:
            image_path = Path(task.content.representative_image.path)
            if not image_path.exists():
                raise ValueError("대표이미지 파일을 찾을 수 없습니다.")
            image_file = _facebook_image_file(image_path)
            response = requests.post(
                f"{graph_root}/photos",
                data={"caption": message, "access_token": token, "published": "true"},
                files={"source": (f"{image_path.stem}.jpg", image_file, "image/jpeg")},
                timeout=60,
            )
            image_file.close()
        else:
            data = {"message": message, "access_token": token}
            if include_link:
                data["link"] = str(payload.get("link"))
            response = requests.post(f"{graph_root}/feed", data=data, timeout=45)

        result = response.json()
        if not response.ok or result.get("error"):
            error = result.get("error") or {}
            raise ValueError(error.get("message") or f"Facebook API 오류 HTTP {response.status_code}")

        external_id = str(result.get("post_id") or result.get("id") or "")
        external_url = f"https://www.facebook.com/{external_id}" if external_id else ""
        return _finish_task(task, queue_id, external_id, external_url)
    except Exception as exc:
        return _fail_task(task, queue_id, str(exc))


def _instagram_image_preflight(image_url: str) -> tuple[bool, str]:
    """Verify that Meta can receive a real public image URL before publishing."""
    try:
        response = requests.get(
            image_url,
            timeout=20,
            allow_redirects=True,
            headers={"User-Agent": "SNSGROWUP-Instagram-Preflight/1.0"},
        )
    except requests.RequestException as exc:
        return False, f"Instagram 대표이미지 공개 URL에 연결할 수 없습니다: {exc}"

    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()

    if response.status_code != 200:
        return False, (
            f"Instagram 대표이미지 URL이 외부에서 열리지 않습니다. "
            f"HTTP {response.status_code}. Codespaces 포트 공개 상태 또는 PUBLIC_BASE_URL을 확인해 주세요."
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if content_type not in allowed_types:
        return False, (
            f"Instagram 대표이미지 URL이 실제 이미지가 아닙니다. "
            f"응답 형식: {content_type or '알 수 없음'}. "
            "로그인 화면이나 HTML 오류 페이지가 반환되는지 확인해 주세요."
        )

    if len(response.content) < 1024:
        return False, "Instagram 대표이미지 파일 크기가 비정상적으로 작습니다."

    return True, ""


@shared_task(bind=True)
def publish_instagram_task(self, publishing_task_id: int, queue_id: int | None = None):
    task = PublishingTask.objects.select_related(
        "batch", "batch__owner", "content", "channel__platform",
    ).get(pk=publishing_task_id)

    if task.channel.platform.code != "instagram":
        return _fail_task(task, queue_id, "Instagram 작업이 아닙니다.")
    if not task.channel.is_connected or not task.channel.access_token or not task.channel.external_account_id:
        return _fail_task(task, queue_id, "Instagram 프로페셔널 계정 연결과 Access Token이 필요합니다.", connection_required=True)
    if "instagram_content_publish" not in (task.channel.granted_scopes or []):
        return _fail_task(task, queue_id, "Instagram 게시 권한(instagram_content_publish)이 없습니다. 채널을 다시 연결해 주세요.", connection_required=True)

    payload = task.payload or {}
    image_url = str(payload.get("image") or "").strip()
    if not image_url.startswith("https://"):
        return _fail_task(task, queue_id, "Instagram 이미지는 Meta가 접근할 수 있는 공개 HTTPS URL이어야 합니다. PUBLIC_BASE_URL 또는 Codespaces 포트 공개 설정을 확인해 주세요.")

    image_ok, image_error = _instagram_image_preflight(image_url)
    if not image_ok:
        return _fail_task(task, queue_id, image_error)

    _start_task(task)
    caption = _final_message(payload)
    ig_user_id = task.channel.external_account_id
    token = task.channel.access_token
    version = settings.FACEBOOK_GRAPH_VERSION
    graph_root = f"https://graph.facebook.com/{version}"

    try:
        create_response = requests.post(
            f"{graph_root}/{ig_user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": token},
            timeout=60,
        )
        create_result = create_response.json()
        if not create_response.ok or create_result.get("error"):
            error = create_result.get("error") or {}
            message = error.get("message") or f"Instagram 컨테이너 생성 오류 HTTP {create_response.status_code}"
            if "image" in message.lower() or "url" in message.lower():
                message += " (이미지 URL이 외부 공개 상태인지 확인하세요.)"
            raise ValueError(message)

        creation_id = str(create_result.get("id") or "")
        if not creation_id:
            raise ValueError("Instagram 미디어 컨테이너 ID를 받지 못했습니다.")

        for _ in range(5):
            status_response = requests.get(
                f"{graph_root}/{creation_id}",
                params={"fields": "status_code,status", "access_token": token},
                timeout=30,
            )
            status_result = status_response.json()
            status_code = str(status_result.get("status_code") or "").upper()
            if status_code in {"FINISHED", "PUBLISHED"}:
                break
            if status_code in {"ERROR", "EXPIRED"}:
                raise ValueError(status_result.get("status") or f"Instagram 컨테이너 상태: {status_code}")
            time.sleep(2)

        publish_response = requests.post(
            f"{graph_root}/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": token},
            timeout=60,
        )
        publish_result = publish_response.json()
        if not publish_response.ok or publish_result.get("error"):
            error = publish_result.get("error") or {}
            raise ValueError(error.get("message") or f"Instagram 게시 오류 HTTP {publish_response.status_code}")

        media_id = str(publish_result.get("id") or "")
        permalink = ""
        if media_id:
            detail = requests.get(
                f"{graph_root}/{media_id}",
                params={"fields": "permalink", "access_token": token},
                timeout=30,
            )
            if detail.ok:
                permalink = str((detail.json() or {}).get("permalink") or "")
        return _finish_task(task, queue_id, media_id, permalink)
    except Exception as exc:
        return _fail_task(task, queue_id, str(exc))


def _youtube_access_token(channel) -> str:
    """Return a valid access token, refreshing and persisting it when needed."""
    token = channel.access_token
    needs_refresh = not token or (channel.token_expires_at and channel.token_expires_at <= timezone.now())
    if not needs_refresh:
        return token
    if not channel.refresh_token:
        raise ValueError("YouTube refresh token이 없습니다. 채널을 다시 연결해 주세요.")
    refreshed = youtube_oauth.refresh_access_token(refresh_token=channel.refresh_token)
    channel.access_token = refreshed["access_token"]
    channel.token_expires_at = youtube_oauth.expiry_datetime(refreshed)
    channel.save(update_fields=["access_token", "token_expires_at", "updated_at"])
    return channel.access_token


_YOUTUBE_TAG_STOPWORDS = {
    "대한", "관련", "통해", "위해", "이번", "오는", "지난", "기자", "뉴스", "밝혔습니다",
    "밝혔다", "예정", "진행", "개최", "운영", "추진", "그리고", "하지만", "있습니다", "했습니다",
}
_YOUTUBE_TAG_SUFFIXES = ("에서", "으로", "에게", "까지", "부터", "에는", "으로는", "이라는", "이라고", "이라며", "의", "은", "는", "이", "가", "을", "를", "와", "과", "도")


def _normalize_youtube_tag(token: str) -> str:
    value = token.strip("-_.,·'\"()[]{}<>:;!?/\\")
    for suffix in _YOUTUBE_TAG_SUFFIXES:
        if len(value) >= 4 and value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value[:30]


def _youtube_tags(*, title: str, body: str, payload: dict) -> list[str]:
    """Extract stable per-article YouTube tags without an extra AI/API call."""
    tags: list[str] = ["Shorts", "SNSGROWUP", "뉴스"]

    existing_hashtags = re.findall(r"#([0-9A-Za-z가-힣_\-]{2,30})", str(payload.get("hashtags") or ""))
    tags.extend(existing_hashtags)

    title_tokens = re.findall(r"[0-9A-Za-z가-힣]{2,30}", title or "")
    body_tokens = re.findall(r"[0-9A-Za-z가-힣]{2,30}", (body or "")[:2500])
    weighted = Counter()
    for token in title_tokens:
        normalized = _normalize_youtube_tag(token)
        if len(normalized) >= 2 and normalized not in _YOUTUBE_TAG_STOPWORDS:
            weighted[normalized] += 5
    for token in body_tokens:
        normalized = _normalize_youtube_tag(token)
        if len(normalized) >= 2 and normalized not in _YOUTUBE_TAG_STOPWORDS:
            weighted[normalized] += 1

    tags.extend(tag for tag, _score in weighted.most_common(12))

    unique: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = re.sub(r"\s+", " ", str(tag)).strip().lstrip("#")
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        unique.append(clean[:30])
        if len(unique) >= 12:
            break
    return unique


def _youtube_upload(*, access_token: str, video_path: Path, title: str, description: str, tags: list[str] | None = None) -> dict:
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "25",
            "tags": list(tags or [])[:12],
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(video_path.stat().st_size),
        },
        json=metadata,
        timeout=45,
    )
    if not init.ok:
        try:
            detail = init.json()
        except ValueError:
            detail = init.text
        raise ValueError(f"YouTube 업로드 세션 생성 실패: {detail}")
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise ValueError("YouTube resumable upload URL을 받지 못했습니다.")

    with video_path.open("rb") as video_file:
        uploaded = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4"},
            data=video_file,
            timeout=180,
        )
    try:
        result = uploaded.json()
    except ValueError:
        result = {}
    if not uploaded.ok:
        raise ValueError(f"YouTube 영상 업로드 실패: {result or uploaded.text}")
    return result


@shared_task(bind=True)
def publish_youtube_short_task(self, publishing_task_id: int, queue_id: int | None = None):
    task = PublishingTask.objects.select_related(
        "batch", "batch__owner", "content", "channel__platform",
    ).get(pk=publishing_task_id)

    if task.channel.platform.code != "youtube":
        return _fail_task(task, queue_id, "YouTube 작업이 아닙니다.")
    if not task.channel.is_connected or not task.channel.external_account_id:
        return _fail_task(task, queue_id, "YouTube 공식 API 연결이 필요합니다.", connection_required=True)
    if "https://www.googleapis.com/auth/youtube.upload" not in (task.channel.granted_scopes or []):
        return _fail_task(task, queue_id, "YouTube 업로드 권한(youtube.upload)이 없습니다. 채널을 다시 연결해 주세요.", connection_required=True)
    if not task.content.representative_image:
        return _fail_task(task, queue_id, "YouTube 쇼츠 생성에는 대표이미지가 필요합니다.")

    _start_task(task)
    payload = task.payload or {}
    try:
        video_path, script = generate_news_short(content=task.content, task_id=task.pk)
        token = _youtube_access_token(task.channel)
        tags = _youtube_tags(
            title=task.content.title,
            body=task.content.body,
            payload=payload,
        )
        hashtags = " ".join(f"#{tag.replace(' ', '')}" for tag in tags if tag != "SNSGROWUP")
        description_parts = [
            script,
            str(payload.get("message") or "").strip(),
            str(payload.get("link") or task.content.source_url or "").strip(),
            hashtags,
        ]
        description = "\n\n".join(part for part in description_parts if part)
        result = _youtube_upload(
            access_token=token,
            video_path=video_path,
            title=task.content.title,
            description=description,
            tags=tags,
        )
        video_id = str(result.get("id") or "")
        if not video_id:
            raise ValueError("YouTube가 업로드된 영상 ID를 반환하지 않았습니다.")
        payload["youtube_short_script"] = script
        payload["generated_video"] = str(video_path.relative_to(settings.MEDIA_ROOT))
        payload["youtube_privacy"] = "public"
        payload["youtube_tags"] = tags
        payload["youtube_hashtags"] = hashtags
        task.payload = payload
        task.save(update_fields=["payload", "updated_at"])
        return _finish_task(task, queue_id, video_id, f"https://www.youtube.com/watch?v={video_id}")
    except (ShortsGenerationError, youtube_oauth.YouTubeOAuthError, Exception) as exc:
        return _fail_task(task, queue_id, str(exc))
