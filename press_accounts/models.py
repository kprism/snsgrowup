from django.conf import settings
from django.db import models


class PressProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="press_profile")
    press_name = models.CharField(max_length=150)
    homepage_url = models.URLField()
    rss_url = models.URLField()
    rss_verified = models.BooleanField(default=False)
    logo = models.ImageField(upload_to="press_logos/", blank=True)
    auto_collect = models.BooleanField(default=True)
    last_collected_at = models.DateTimeField(null=True, blank=True)
    collection_status = models.CharField(max_length=30, default="pending")

    def __str__(self):
        return self.press_name
