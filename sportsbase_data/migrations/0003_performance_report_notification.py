from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sportsbase_data", "0002_youtube_all_actions_delivery"),
    ]

    operations = [
        migrations.AddField(
            model_name="performancereport",
            name="notification_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="performancereport",
            name="notification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
