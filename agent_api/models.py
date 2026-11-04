import uuid

from django.conf import settings
from django.db import models


class AgentAction(models.Model):
    """A reviewed proposal and durable receipt, owned by the authenticated account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=120)
    parameters = models.JSONField(default=dict)
    values = models.JSONField(default=dict)
    baseline = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, default="prepared")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ("-created_at",)
