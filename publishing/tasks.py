from __future__ import annotations

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


@shared_task
def dispatch_due_publish_queues(limit: int = 20):
    """예약시각 또는 재시도시각이 지난 Queue를 Celery 게시 작업으로 넘긴다."""
    now = timezone.now()
    dispatched = []
    with transaction.atomic():
        queues = list(
            PublishQueue.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=PublishQueue.Status.SCHEDULED, scheduled_at__lte=now)
                | Q(status=PublishQueue.Status.RETRY, next_retry_at__lte=now)
            )
            .select_related("task")
            .order_by("scheduled_at", "id")[:limit]
        )
        for queue in queues:
            queue.status = PublishQueue.Status.PROCESSING
            queue.save(update_fields=["status", "updated_at"])
            dispatched.append((queue.task_id, queue.pk))

    for task_id, queue_id in dispatched:
        publish_facebook_task.delay(task_id, queue_id)
    return {"dispatched": len(dispatched)}


@shared_task(bind=True)
def publish_facebook_task(self, publishing_task_id: int, queue_id: int | None = None):
    task = PublishingTask.objects.select_related(
        "batch",
        "batch__owner",
        "content",
        "channel__platform",
    ).get(pk=publishing_task_id)

    if task.channel.platform.code != "facebook":
        task.status = PublishingTask.Status.FAILED
        task.error_message = "Facebook 작업이 아닙니다."
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        _queue_failure(queue_id, task, task.error_message)
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}

    if not task.channel.is_connected or not task.channel.access_token or not task.channel.external_account_id:
        task.status = PublishingTask.Status.CONNECTION_REQUIRED
        task.error_message = "Facebook 페이지 연결 또는 Page Access Token이 필요합니다."
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        _queue_failure(queue_id, task, task.error_message)
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}

    task.status = PublishingTask.Status.PROCESSING
    task.started_at = timezone.now()
    task.finished_at = None
    task.attempt_count += 1
    task.error_message = ""
    task.save(update_fields=["status", "started_at", "finished_at", "attempt_count", "error_message", "updated_at"])
    task.batch.refresh_status()

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
        task.status = PublishingTask.Status.SUCCESS
        task.external_post_id = external_id
        task.external_post_url = f"https://www.facebook.com/{external_id}" if external_id else ""
        task.error_message = ""
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "external_post_id", "external_post_url", "error_message", "finished_at", "updated_at"])
        _queue_success(queue_id)
        task.batch.refresh_status()
        return {"ok": True, "external_post_id": external_id}
    except Exception as exc:
        task.status = PublishingTask.Status.FAILED
        task.error_message = str(exc)[:2000]
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        _queue_failure(queue_id, task, task.error_message)
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}
