from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("publishing", "0002_publishingtask_batch_updates"),
    ]

    operations = [
        migrations.AddField(
            model_name="publishingtask",
            name="payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
