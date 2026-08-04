from django.conf import settings
from django.db import models


class SocialPlatform(models.Model):
    name = models.CharField(max_length=50)
    code = models.SlugField(unique=True)
    icon = models.CharField(max_length=255, blank=True)
    supports_oauth = models.BooleanField(default=False)
    supports_publish = models.BooleanField(default=False)
    supports_analytics = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SocialAccount(models.Model):
    class ConnectionStatus(models.TextChoices):
        URL_ONLY = "url_only", "URL만 등록"
        PENDING = "pending", "연결 대기"
        CONNECTED = "connected", "연결됨"
        REAUTH_REQUIRED = "reauth_required", "재인증 필요"
        ERROR = "error", "연결 오류"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts")
    platform = models.ForeignKey(SocialPlatform, on_delete=models.PROTECT)
    profile_name = models.CharField(max_length=120)
    profile_url = models.URLField()
    external_account_id = models.CharField(max_length=255, blank=True)
    connection_status = models.CharField(
        max_length=30,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.URL_ONLY,
    )
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    last_connection_error = models.TextField(blank=True)
    granted_scopes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "platform", "profile_url")

    @property
    def is_connected(self):
        return self.connection_status == self.ConnectionStatus.CONNECTED
