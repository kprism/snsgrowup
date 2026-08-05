from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("publishing", "0003_publishingtask_payload"),
    ]

    operations = [
        migrations.CreateModel(
            name="AutomationSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("min_interval_seconds", models.PositiveIntegerField(default=48)),
                ("max_interval_seconds", models.PositiveIntegerField(default=90)),
                ("use_random_delay", models.BooleanField(default=True)),
                ("retry_enabled", models.BooleanField(default=True)),
                ("use_ai", models.BooleanField(default=True)),
                ("auto_tags", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="automation_setting", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "자동발행 설정",
                "verbose_name_plural": "자동발행 설정",
            },
        ),
    ]
