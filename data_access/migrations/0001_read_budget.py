"""Explicit technical-only migration; deployment approval is required."""
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="ReadBudget",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False, verbose_name="ID")),
                ("principal_hash", models.CharField(max_length=64)),
                ("window_start", models.DateTimeField()),
                ("requests", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "data_access_read_budget",
                "indexes": [models.Index(fields=["window_start"], name="da_budget_window_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=("principal_hash", "window_start"), name="da_budget_principal_window_uniq"),
                    models.CheckConstraint(check=models.Q(requests__gte=0), name="da_budget_requests_nonnegative"),
                ],
            },
        ),
    ]
