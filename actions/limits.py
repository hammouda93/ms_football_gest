"""Shared SQL quotas. Called only before the owned business transaction."""
from datetime import timedelta
from django.conf import settings
from django.db import connection,transaction
from .models import QuotaBucket

class QuotaExceeded(Exception):
    pass

def setting(name,default,maximum):
    value=getattr(settings,name,default)
    if type(value) is not int or not 1<=value<=maximum:
        raise ValueError('invalid_writer_limit')
    return value

def reserve(actor):
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError('transaction_owned_externally')
    window=setting('ACTIONS_QUOTA_WINDOW_SECONDS',60,3600)
    limits=[('global',setting('ACTIONS_QUOTA_GLOBAL',60,10000)),('actor:'+str(actor),setting('ACTIONS_QUOTA_IDENTITY',10,10000))]
    with transaction.atomic(durable=True):
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, true),set_config('lock_timeout', %s, true)",['1000ms','200ms'])
            # One constant transaction lock serializes both buckets and first insertion.
            cursor.execute('SELECT pg_advisory_xact_lock(174651,6)')
            cursor.execute('SELECT clock_timestamp()')
            now=cursor.fetchone()[0]
        buckets=[]
        for key,limit in limits:
            bucket,_=QuotaBucket.objects.get_or_create(key=key,defaults={'window_start':now})
            if now>=bucket.window_start+timedelta(seconds=window):
                bucket.window_start=now;bucket.used=0
            if bucket.used>=limit:raise QuotaExceeded()
            buckets.append(bucket)
        for bucket in buckets:
            bucket.used+=1;bucket.save(update_fields=['window_start','used'])
