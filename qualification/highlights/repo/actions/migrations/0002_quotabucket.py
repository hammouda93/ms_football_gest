from django.db import migrations,models

class Migration(migrations.Migration):
    dependencies=[('actions','0001_initial')]
    operations=[migrations.CreateModel(name='QuotaBucket',fields=[('key',models.CharField(max_length=80,primary_key=True,serialize=False)),('window_start',models.DateTimeField()),('used',models.PositiveIntegerField(default=0))])]
