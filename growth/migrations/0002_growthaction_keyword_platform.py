from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="growthaction",
            name="keyword",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="growthaction",
            name="platform",
            field=models.CharField(default="instagram", max_length=30),
        ),
    ]
