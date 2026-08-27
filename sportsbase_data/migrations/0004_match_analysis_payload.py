from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sportsbase_data", "0003_performance_report_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsbasematchstats",
            name="players_statistics_headers",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="sportsbasematchstats",
            name="players_statistics_rows",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="performancereport",
            name="analysis_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
