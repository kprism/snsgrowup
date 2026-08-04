from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("social_channels", "0002_seed_default_platforms"),
    ]

    operations = [
        migrations.AddField(model_name="socialaccount", name="access_token", field=models.TextField(blank=True)),
        migrations.AddField(model_name="socialaccount", name="refresh_token", field=models.TextField(blank=True)),
        migrations.AddField(model_name="socialaccount", name="token_expires_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="socialaccount", name="connected_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="socialaccount", name="last_connection_error", field=models.TextField(blank=True)),
        migrations.AddField(model_name="socialaccount", name="granted_scopes", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="socialaccount", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AlterField(
            model_name="socialaccount",
            name="connection_status",
            field=models.CharField(
                choices=[
                    ("url_only", "URL만 등록"),
                    ("pending", "연결 대기"),
                    ("connected", "연결됨"),
                    ("reauth_required", "재인증 필요"),
                    ("error", "연결 오류"),
                ],
                default="url_only",
                max_length=30,
            ),
        ),
    ]
