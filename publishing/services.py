import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import AutomationSetting, PublishQueue, PublishingBatch, PublishingTask


def _task_defaults(channel):
    if channel.connection_status == "connected":
        return PublishingTask.Status.PENDING, ""
    return (
        PublishingTask.Status.CONNECTION_REQUIRED,
        "공식 API 연결이 필요합니다. 채널 연결을 완료한 뒤 재시도해 주세요.",
    )


@transaction.atomic
def ensure_batch_tasks(*, batch: PublishingBatch, task_payloads=None):
    """기존 배치에도 콘텐츠×채널 조합의 개별 작업이 빠짐없이 존재하도록 보정한다."""
    contents = list(batch.contents.all())
    channels = list(batch.channels.select_related("platform").all())
    existing = set(batch.tasks.values_list("content_id", "channel_id"))
    task_payloads = task_payloads or {}

    tasks = []
    for content in contents:
        for channel in channels:
            key = (content.pk, channel.pk)
            if key in existing:
                continue
            status, error_message = _task_defaults(channel)
            tasks.append(
                PublishingTask(
                    batch=batch,
                    content=content,
                    channel=channel,
                    status=status,
                    error_message=error_message,
                    payload=task_payloads.get(key, {}),
                )
            )

    if tasks:
        PublishingTask.objects.bulk_create(tasks, ignore_conflicts=True)
    batch.refresh_status()
    return len(tasks)


@transaction.atomic
def create_publishing_batch(*, owner, contents, channels, action, task_payloads=None):
    selected_contents = list(contents)
    selected_channels = list(channels)

    batch = PublishingBatch.objects.create(owner=owner, action=action)
    batch.contents.set(selected_contents)
    batch.channels.set(selected_channels)
    ensure_batch_tasks(batch=batch, task_payloads=task_payloads)
    return batch


@transaction.atomic
def enqueue_batch_tasks(*, batch: PublishingBatch):
    """게시 가능한 작업을 사용자 간격 설정에 맞춰 순차 Queue로 등록한다."""
    setting, _ = AutomationSetting.objects.get_or_create(owner=batch.owner)
    minimum = max(1, setting.min_interval_seconds)
    maximum = max(minimum, setting.max_interval_seconds)
    cursor = timezone.now()
    created = 0

    tasks = batch.tasks.select_related("channel__platform").filter(status=PublishingTask.Status.PENDING)
    for task in tasks:
        if task.channel.platform.code not in {"facebook", "instagram", "youtube"}:
            continue
        delay = random.randint(minimum, maximum) if setting.use_random_delay else minimum
        cursor += timedelta(seconds=delay)
        _, was_created = PublishQueue.objects.get_or_create(
            task=task,
            defaults={
                "scheduled_at": cursor,
                "random_delay": delay,
                "status": PublishQueue.Status.SCHEDULED,
            },
        )
        created += int(was_created)

    if created and not batch.scheduled_at:
        first_queue = PublishQueue.objects.filter(task__batch=batch).order_by("scheduled_at").first()
        if first_queue:
            batch.scheduled_at = first_queue.scheduled_at
            batch.save(update_fields=["scheduled_at", "updated_at"])
    return created


@transaction.atomic
def retry_task(*, task: PublishingTask):
    status, error_message = _task_defaults(task.channel)
    task.status = status
    task.error_message = error_message
    task.save(update_fields=["status", "error_message", "updated_at"])
    queue = PublishQueue.objects.filter(task=task).first()
    if queue:
        queue.status = PublishQueue.Status.SCHEDULED
        queue.scheduled_at = timezone.now()
        queue.next_retry_at = None
        queue.last_error = ""
        queue.save(update_fields=["status", "scheduled_at", "next_retry_at", "last_error", "updated_at"])
    task.batch.refresh_status()
    return task
