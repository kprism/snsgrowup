from django.db import transaction

from contents.models import ContentItem
from social_channels.models import SocialAccount

from .models import PublishingBatch, PublishingTask


@transaction.atomic
def create_publishing_batch(*, owner, contents, channels, action):
    selected_contents = list(contents)
    selected_channels = list(channels)

    batch = PublishingBatch.objects.create(owner=owner, action=action)
    batch.contents.set(selected_contents)
    batch.channels.set(selected_channels)

    tasks = []
    for content in selected_contents:
        for channel in selected_channels:
            status = PublishingTask.Status.PENDING
            error_message = ""
            if channel.connection_status != "connected":
                status = PublishingTask.Status.CONNECTION_REQUIRED
                error_message = "공식 API 연결이 필요합니다. 채널 연결을 완료한 뒤 재시도해 주세요."
            tasks.append(
                PublishingTask(
                    batch=batch,
                    content=content,
                    channel=channel,
                    status=status,
                    error_message=error_message,
                )
            )

    PublishingTask.objects.bulk_create(tasks)
    batch.refresh_status()
    return batch


@transaction.atomic
def retry_task(*, task: PublishingTask):
    if task.channel.connection_status != "connected":
        task.status = PublishingTask.Status.CONNECTION_REQUIRED
        task.error_message = "공식 API 연결이 필요합니다."
    else:
        task.status = PublishingTask.Status.PENDING
        task.error_message = ""
    task.save(update_fields=["status", "error_message", "updated_at"])
    task.batch.refresh_status()
    return task
