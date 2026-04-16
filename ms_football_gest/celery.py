""" from __future__ import absolute_import, unicode_literals """
import os
from celery import Celery
from celery.schedules import crontab
""" from django.conf import settings
import django """

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')

""" django.setup() """ 
""" app = Celery('ms_football_gest',broker='redis://127.0.0.1:6380/0') """
app = Celery('ms_football_gest')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

@app.task(blind=True, ignore_result=True )
def debug_task(self):
    print(f'Request: {self.request!r}')
