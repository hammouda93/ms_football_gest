from django.db import migrations,models
import django.db.models.deletion,uuid
class Migration(migrations.Migration):
 dependencies=[('actions','0002_quotabucket')]
 operations=[migrations.CreateModel(name='Verification',fields=[('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),('actor_id',models.PositiveIntegerField()),('body',models.JSONField()),('mac',models.CharField(max_length=64)),('expires_at',models.DateTimeField()),('created_at',models.DateTimeField(auto_now_add=True)),('plan',models.ForeignKey(to='actions.plan',on_delete=django.db.models.deletion.PROTECT))])]
