"""Technical counters only: no business relationships or request contents."""
from django.db import models


class ReadBudget(models.Model):
    id = models.AutoField(primary_key=True, serialize=False, verbose_name="ID")
    principal_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    requests = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "data_access_read_budget"
        constraints = [
            models.UniqueConstraint(fields=("principal_hash", "window_start"), name="da_budget_principal_window_uniq"),
            models.CheckConstraint(check=models.Q(requests__gte=0), name="da_budget_requests_nonnegative"),
        ]
        indexes = [models.Index(fields=("window_start",), name="da_budget_window_idx")]
