from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contents", "0001_initial"),
        ("publishing", "0001_initial"),
        ("social_channels", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="publishingbatch",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="publishingbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "대기"),
                    ("processing", "진행 중"),
                    ("completed", "완료"),
                    ("partial", "일부 실패"),
                    ("failed", "실패"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="PublishingTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("pending", "대기"), ("connection_required", "연결 필요"), ("processing", "처리 중"), ("success", "성공"), ("failed", "실패")], default="pending", max_length=30)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True)),
                ("external_post_id", models.CharField(blank=True, max_length=255)),
                ("external_post_url", models.URLField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks", to="publishing.publishingbatch")),
                ("channel", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publishing_tasks", to="social_channels.socialaccount")),
                ("content", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="publishing_tasks", to="contents.contentitem")),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="publishingtask",
            constraint=models.UniqueConstraint(fields=("batch", "content", "channel"), name="unique_batch_content_channel"),
        ),
    ]
