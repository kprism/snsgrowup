from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("growth", "0002_growthaction_keyword_platform"),
        ("social_channels", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelMetricSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform", models.CharField(max_length=30)),
                ("followers_count", models.PositiveBigIntegerField(blank=True, null=True)),
                ("reactions_count", models.PositiveBigIntegerField(blank=True, null=True)),
                ("comments_count", models.PositiveBigIntegerField(blank=True, null=True)),
                ("completed_actions_count", models.PositiveIntegerField(default=0)),
                ("collected_at", models.DateTimeField(auto_now_add=True)),
                ("collection_ok", models.BooleanField(default=True)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_metric_snapshots", to=settings.AUTH_USER_MODEL)),
                ("social_account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="metric_snapshots", to="social_channels.socialaccount")),
            ],
            options={"ordering": ["-collected_at"]},
        ),
        migrations.AddIndex(
            model_name="channelmetricsnapshot",
            index=models.Index(fields=["social_account", "-collected_at"], name="growth_chan_social__73ac87_idx"),
        ),
        migrations.AddIndex(
            model_name="channelmetricsnapshot",
            index=models.Index(fields=["owner", "platform", "-collected_at"], name="growth_chan_owner_i_1b219b_idx"),
        ),
    ]
