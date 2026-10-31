"""Read-only fixture census and exact target identity in a separate process."""
import os,sys,json
from pathlib import Path
R=Path(__file__).resolve().parent
sys.path[:0]=[str(R),str(R/'source')];os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install
install()
from lab_control import identity
who=identity()
import django
django.setup()
from django.db import connection,transaction
from django.contrib.auth import get_user_model
from django.apps import apps
with transaction.atomic():
 with connection.cursor() as q:
  q.execute('SET TRANSACTION READ ONLY');q.execute('SET LOCAL statement_timeout=5000')
  q.execute("select pg_backend_pid(),current_setting('transaction_read_only'),version()")
  runtime=q.fetchone()
 counts={m._meta.label:m.objects.count() for m in apps.get_models()}
 admins=get_user_model().objects.filter(is_superuser=True).count()
print(json.dumps({'pid':os.getpid(),'identity':who,'runtime':runtime,'superusers':admins,'model_counts':counts}))
