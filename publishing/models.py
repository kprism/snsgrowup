from django.conf import settings
from django.db import models

from contents.models import ContentItem
from social_channels.models import SocialAccount


class PublishingBatch(models.Model):
    class Action(models.TextChoices):
        UPLOAD = "upload", "SNS 업로드"
        SCHEDULE = "schedule", "예약 발행"
        SHORTS = "shorts", "AI 5초 쇼츠 생성"

    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        PROCESSING = "processing", "진행 중"
        COMPLETED = "completed", "완료"
        PARTIAL = "partial", "일부 실패"
        FAILED = "failed", "실패"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="publishing_batches")
    contents = models.ManyToManyField(ContentItem, related_name="publishing_batches")
    channels = models.ManyToManyField(SocialAccount, related_name="publishing_batches")
    action = models.CharField(max_length=20, choices=Action.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    result_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.owner} · {self.get_action_display()} · {self.created_at:%Y-%m-%d %H:%M}"

    def refresh_status(self):
        statuses = list(self.tasks.values_list("status", flat=True))
        if not statuses:
            self.status = self.Status.PENDING
        elif all(status == PublishingTask.Status.SUCCESS for status in statuses):
            self.status = self.Status.COMPLETED
        elif all(status == PublishingTask.Status.FAILED for status in statuses):
            self.status = self.Status.FAILED
        elif any(status == PublishingTask.Status.PROCESSING for status in statuses):
            self.status = self.Status.PROCESSING
        elif any(status == PublishingTask.Status.FAILED for status in statuses):
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.PENDING
        self.save(update_fields=["status", "updated_at"])


class PublishingTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "대기"
        CONNECTION_REQUIRED = "connection_required", "연결 필요"
        PROCESSING = "processing", "처리 중"
        SUCCESS = "success", "성공"
        FAILED = "failed", "실패"

    batch = models.ForeignKey(PublishingBatch, on_delete=models.CASCADE, related_name="tasks")
    content = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name="publishing_tasks")
    channel = models.ForeignKey(SocialAccount, on_delete=models.CASCADE, related_name="publishing_tasks")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    external_post_id = models.CharField(max_length=255, blank=True)
    external_post_url = models.URLField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "content", "channel"],
                name="unique_batch_content_channel",
            )
        ]

    def __str__(self):
        return f"#{self.batch_id} · {self.content.title} · {self.channel.profile_name}"


class AutomationSetting(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="automation_setting",
    )
    enabled = models.BooleanField(default=False)
    min_interval_seconds = models.PositiveIntegerField(default=48)
    max_interval_seconds = models.PositiveIntegerField(default=90)
    use_random_delay = models.BooleanField(default=True)
    retry_enabled = models.BooleanField(default=True)
    use_ai = models.BooleanField(default=True)
    auto_tags = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "자동발행 설정"
        verbose_name_plural = "자동발행 설정"

    def __str__(self):
        return f"{self.owner} 자동발행 설정"


class PublishQueue(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "예정"
        PROCESSING = "processing", "게시 중"
        COMPLETED = "completed", "완료"
        RETRY = "retry", "재시도 예정"
        FAILED = "failed", "실패"
        CANCELLED = "cancelled", "취소"

    task = models.OneToOneField(
        PublishingTask,
        on_delete=models.CASCADE,
        related_name="publish_queue",
    )
    scheduled_at = models.DateTimeField(db_index=True)
    retry_count = models.PositiveIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    random_delay = models.PositiveIntegerField(default=0, help_text="초 단위")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at", "id"]
        indexes = [models.Index(fields=["status", "scheduled_at"])]

    def __str__(self):
        return f"Queue #{self.pk} · Task #{self.task_id} · {self.get_status_display()}"
