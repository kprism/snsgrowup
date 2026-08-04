from django.db import migrations


def seed_platforms(apps, schema_editor):
    SocialPlatform = apps.get_model("social_channels", "SocialPlatform")
    platforms = [
        {"name": "Facebook", "code": "facebook", "supports_oauth": True, "supports_publish": True, "supports_analytics": True},
        {"name": "Instagram", "code": "instagram", "supports_oauth": True, "supports_publish": True, "supports_analytics": True},
        {"name": "YouTube", "code": "youtube", "supports_oauth": True, "supports_publish": True, "supports_analytics": True},
        {"name": "Threads", "code": "threads", "supports_oauth": True, "supports_publish": True, "supports_analytics": True},
    ]
    for item in platforms:
        SocialPlatform.objects.update_or_create(code=item["code"], defaults=item)


def unseed_platforms(apps, schema_editor):
    SocialPlatform = apps.get_model("social_channels", "SocialPlatform")
    SocialPlatform.objects.filter(code__in=["facebook", "instagram", "youtube", "threads"]).delete()


class Migration(migrations.Migration):
    dependencies = [("social_channels", "0001_initial")]
    operations = [migrations.RunPython(seed_platforms, unseed_platforms)]
