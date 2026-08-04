from django.db import transaction

from .models import PublishingBatch, PublishingTask


def _task_defaults(channel):
    if channel.connection_status == "connected":
        return PublishingTask.Status.PENDING, ""
    return (
        PublishingTask.Status.CONNECTION_REQUIRED,
        "공식 API 연결이 필요합니다. 채널 연결을 완료한 뒤 재시도해 주세요.",
    )


@transaction.atomic
def ensure_batch_tasks(*, batch: PublishingBatch):
    """기존 배치에도 콘텐츠×채널 조합의 개별 작업이 빠짐없이 존재하도록 보정한다."""
    contents = list(batch.contents.all())
    channels = list(batch.channels.select_related("platform").all())
    existing = set(batch.tasks.values_list("content_id", "channel_id"))

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
                )
            )

    if tasks:
        PublishingTask.objects.bulk_create(tasks, ignore_conflicts=True)
    batch.refresh_status()
    return len(tasks)


@transaction.atomic
def create_publishing_batch(*, owner, contents, channels, action):
    selected_contents = list(contents)
    selected_channels = list(channels)

    batch = PublishingBatch.objects.create(owner=owner, action=action)
    batch.contents.set(selected_contents)
    batch.channels.set(selected_channels)
    ensure_batch_tasks(batch=batch)
    return batch


@transaction.atomic
def retry_task(*, task: PublishingTask):
    status, error_message = _task_defaults(task.channel)
    task.status = status
    task.error_message = error_message
    task.save(update_fields=["status", "error_message", "updated_at"])
    task.batch.refresh_status()
    return task
