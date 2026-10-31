import uuid
from django.db import models

class QuotaBucket(models.Model):
    key=models.CharField(max_length=80,primary_key=True)
    window_start=models.DateTimeField()
    used=models.PositiveIntegerField(default=0)

class Plan(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    actor_id=models.PositiveIntegerField()
    key=models.CharField(max_length=80)
    digest=models.CharField(max_length=64)
    steps=models.JSONField()
    snapshots=models.JSONField(default=dict)
    state=models.CharField(max_length=20,default='prepared')
    results=models.JSONField(default=dict)
    effects=models.JSONField(default=dict)
    error=models.CharField(max_length=60,default='')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['actor_id','key'],name='action01_idempotency')]
class Audit(models.Model):
    plan=models.ForeignKey(Plan,on_delete=models.PROTECT,null=True)
    actor_id=models.PositiveIntegerField()
    event=models.CharField(max_length=30)
    code=models.CharField(max_length=60,default='')
    created_at=models.DateTimeField(auto_now_add=True)
