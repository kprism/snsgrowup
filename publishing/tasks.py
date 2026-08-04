from __future__ import annotations

from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import PublishingTask


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


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def publish_facebook_task(self, publishing_task_id: int):
    task = PublishingTask.objects.select_related(
        "batch",
        "content",
        "channel__platform",
    ).get(pk=publishing_task_id)

    if task.channel.platform.code != "facebook":
        task.status = PublishingTask.Status.FAILED
        task.error_message = "Facebook 작업이 아닙니다."
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}

    if not task.channel.is_connected or not task.channel.access_token or not task.channel.external_account_id:
        task.status = PublishingTask.Status.CONNECTION_REQUIRED
        task.error_message = "Facebook 페이지 연결 또는 Page Access Token이 필요합니다."
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}

    task.status = PublishingTask.Status.PROCESSING
    task.started_at = timezone.now()
    task.finished_at = None
    task.attempt_count += 1
    task.error_message = ""
    task.save(
        update_fields=[
            "status",
            "started_at",
            "finished_at",
            "attempt_count",
            "error_message",
            "updated_at",
        ]
    )
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
                data={
                    "caption": message,
                    "access_token": token,
                    "published": "true",
                },
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
        task.save(
            update_fields=[
                "status",
                "external_post_id",
                "external_post_url",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        task.batch.refresh_status()
        return {"ok": True, "external_post_id": external_id}
    except Exception as exc:
        task.status = PublishingTask.Status.FAILED
        task.error_message = str(exc)[:2000]
        task.finished_at = timezone.now()
        task.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        task.batch.refresh_status()
        return {"ok": False, "message": task.error_message}
