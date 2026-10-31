import uuid
import django.db.models.deletion
from django.db import migrations,models

class Migration(migrations.Migration):
 initial=True
 dependencies=[]
 operations=[
  migrations.CreateModel(name='Plan',fields=[
   ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
   ('actor_id',models.PositiveIntegerField()),('key',models.CharField(max_length=80)),
   ('digest',models.CharField(max_length=64)),('steps',models.JSONField()),
   ('snapshots',models.JSONField(default=dict)),('state',models.CharField(max_length=20,default='prepared')),
   ('results',models.JSONField(default=dict)),('effects',models.JSONField(default=dict)),
   ('error',models.CharField(max_length=60,default='')),('created_at',models.DateTimeField(auto_now_add=True))
  ],options={'constraints':[models.UniqueConstraint(fields=('actor_id','key'),name='action01_idempotency')]}),
  migrations.CreateModel(name='Audit',fields=[
   ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
   ('actor_id',models.PositiveIntegerField()),('event',models.CharField(max_length=30)),
   ('code',models.CharField(max_length=60,default='')),('created_at',models.DateTimeField(auto_now_add=True)),
   ('plan',models.ForeignKey(null=True,on_delete=django.db.models.deletion.PROTECT,to='actions.plan'))
  ])
 ]
