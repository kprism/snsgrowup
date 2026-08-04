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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts")
    platform = models.ForeignKey(SocialPlatform, on_delete=models.PROTECT)
    profile_name = models.CharField(max_length=120)
    profile_url = models.URLField()
    external_account_id = models.CharField(max_length=255, blank=True)
    connection_status = models.CharField(max_length=30, default="url_only")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "platform", "profile_url")
