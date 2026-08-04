# Generated manually for SNSGROWUP
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("contents", "0001_initial"),
        ("social_channels", "0002_seed_default_platforms"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublishingBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("upload", "SNS 업로드"), ("schedule", "예약 발행"), ("shorts", "AI 5초 쇼츠 생성")], max_length=20)),
                ("status", models.CharField(choices=[("pending", "대기"), ("processing", "진행 중"), ("completed", "완료"), ("failed", "실패")], default="pending", max_length=20)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("result_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("channels", models.ManyToManyField(related_name="publishing_batches", to="social_channels.socialaccount")),
                ("contents", models.ManyToManyField(related_name="publishing_batches", to="contents.contentitem")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publishing_batches", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
