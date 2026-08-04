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
        FAILED = "failed", "실패"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="publishing_batches")
    contents = models.ManyToManyField(ContentItem, related_name="publishing_batches")
    channels = models.ManyToManyField(SocialAccount, related_name="publishing_batches")
    action = models.CharField(max_length=20, choices=Action.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    result_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.owner} · {self.get_action_display()} · {self.created_at:%Y-%m-%d %H:%M}"
