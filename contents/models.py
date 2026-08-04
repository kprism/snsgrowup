from django.conf import settings
from django.db import models


class ContentItem(models.Model):
    class SourceType(models.TextChoices):
        DIRECT = "direct", "직접 등록"
        RSS = "rss", "RSS 기사"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contents")
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    representative_image = models.ImageField(upload_to="article_images/", blank=True)
    external_guid = models.CharField(max_length=500, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "external_guid"], condition=~models.Q(external_guid=""), name="unique_owner_guid")
        ]
