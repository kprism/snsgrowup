from django.conf import settings
from django.db import models


class GrowthAction(models.Model):
    class ActionType(models.TextChoices):
        POST = "post", "게시"
        LIKE = "like", "좋아요"
        COMMENT = "comment", "댓글"
        FOLLOW = "follow", "팔로우"
        STORY = "story", "스토리 보기"

    class Status(models.TextChoices):
        READY = "ready", "실행 전"
        STARTED = "started", "실행 중"
        COMPLETED = "completed", "완료"
        SKIPPED = "skipped", "건너뜀"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="growth_actions")
    platform = models.CharField(max_length=30, default="instagram")
    keyword = models.CharField(max_length=120, blank=True)
    action_type = models.CharField(max_length=20, choices=ActionType.choices)
    title = models.CharField(max_length=200)
    target_url = models.URLField()
    target_label = models.CharField(max_length=120, blank=True)
    recommendation_reason = models.CharField(max_length=255, blank=True)
    priority_score = models.PositiveSmallIntegerField(default=50)
    suggested_comment = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priority_score", "id"]

    def __str__(self):
        return f"{self.owner} · {self.get_action_type_display()} · {self.title}"


class ChannelMetricSnapshot(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_metric_snapshots")
    social_account = models.ForeignKey("social_channels.SocialAccount", on_delete=models.CASCADE, related_name="metric_snapshots")
    platform = models.CharField(max_length=30)
    followers_count = models.PositiveBigIntegerField(null=True, blank=True)
    reactions_count = models.PositiveBigIntegerField(null=True, blank=True)
    comments_count = models.PositiveBigIntegerField(null=True, blank=True)
    completed_actions_count = models.PositiveIntegerField(default=0)
    collected_at = models.DateTimeField(auto_now_add=True)
    collection_ok = models.BooleanField(default=True)
    error_message = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-collected_at"]
        indexes = [
            models.Index(fields=["social_account", "-collected_at"], name="growth_chan_social__73ac87_idx"),
            models.Index(fields=["owner", "platform", "-collected_at"], name="growth_chan_owner_i_1b219b_idx"),
        ]

    def __str__(self):
        return f"{self.social_account} · {self.collected_at:%Y-%m-%d %H:%M}"
