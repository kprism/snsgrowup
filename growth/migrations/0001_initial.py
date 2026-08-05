from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="GrowthAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_type", models.CharField(choices=[("post", "게시"), ("like", "좋아요"), ("comment", "댓글"), ("follow", "팔로우"), ("story", "스토리 보기")], max_length=20)),
                ("title", models.CharField(max_length=200)),
                ("target_url", models.URLField()),
                ("target_label", models.CharField(blank=True, max_length=120)),
                ("recommendation_reason", models.CharField(blank=True, max_length=255)),
                ("priority_score", models.PositiveSmallIntegerField(default=50)),
                ("suggested_comment", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("ready", "실행 전"), ("started", "실행 중"), ("completed", "완료"), ("skipped", "건너뜀")], default="ready", max_length=20)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="growth_actions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-priority_score", "id"]},
        )
    ]
