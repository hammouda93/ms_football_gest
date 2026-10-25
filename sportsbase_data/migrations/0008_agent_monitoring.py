# Generated for the isolated Performance monitoring module.
import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("sportsbase_data", "0007_dailymotion_manual_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="PerformanceAgentRun",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("run_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("worker_name", models.CharField(max_length=100)),
                ("state", models.CharField(default="running", max_length=16)),
                ("planned_jobs", models.PositiveIntegerField(default=0)),
                ("current_job_id", models.PositiveIntegerField(blank=True, null=True)),
                ("current_player", models.CharField(blank=True, max_length=160)),
                ("current_stage", models.CharField(blank=True, max_length=80)),
                ("current_match_id", models.CharField(blank=True, max_length=32)),
                ("last_seen_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ("-started_at", "-pk"),
                "verbose_name": "Session supervision Performance",
            },
        ),
        migrations.CreateModel(
            name="PerformanceAgentEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("sequence", models.PositiveIntegerField()),
                ("kind", models.CharField(max_length=24)),
                ("level", models.CharField(default="info", max_length=12)),
                ("message", models.CharField(max_length=320)),
                ("player", models.CharField(blank=True, max_length=160)),
                ("job_id", models.PositiveIntegerField(blank=True, null=True)),
                ("match_id", models.CharField(blank=True, max_length=32)),
                ("stage", models.CharField(blank=True, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="events", to="sportsbase_data.performanceagentrun")),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
                "verbose_name": "Événement supervision Performance",
            },
        ),
        migrations.AddConstraint(
            model_name="performanceagentevent",
            constraint=models.UniqueConstraint(fields=("run", "sequence"), name="performance_monitor_event_once"),
        ),
        migrations.AddIndex(
            model_name="performanceagentevent",
            index=models.Index(fields=["run", "-created_at"], name="perfmon_run_date_idx"),
        ),
    ]
