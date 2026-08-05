from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("publishing", "0004_automationsetting"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublishQueue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scheduled_at", models.DateTimeField(db_index=True)),
                ("retry_count", models.PositiveIntegerField(default=0)),
                ("next_retry_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("random_delay", models.PositiveIntegerField(default=0, help_text="초 단위")),
                ("status", models.CharField(choices=[("scheduled", "예정"), ("processing", "게시 중"), ("completed", "완료"), ("retry", "재시도 예정"), ("failed", "실패"), ("cancelled", "취소")], db_index=True, default="scheduled", max_length=20)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("task", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="publish_queue", to="publishing.publishingtask")),
            ],
            options={
                "ordering": ["scheduled_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="publishqueue",
            index=models.Index(fields=["status", "scheduled_at"], name="publishing_status_55b93c_idx"),
        ),
    ]
