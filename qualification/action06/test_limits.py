"""Real PostgreSQL operational writer tests; committed fixtures, no caller atomic."""
import hashlib,json,secrets,unittest,uuid
from datetime import timedelta
from django.test import Client,override_settings
from django.conf import settings
from django.db import connection,transaction
from django.utils import timezone
from django.contrib.auth.models import User

class LimitsTests(unittest.TestCase):
    def setUp(self):
        self.actor=User.objects.create(username='FICTION_LIMIT_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        self.token=secrets.token_hex(32)
        self.config=override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+('a'*40),ACTIONS_CREDENTIALS={hashlib.sha256(self.token.encode()).hexdigest():{'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status','op:player.create'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}},MIDDLEWARE=[m.replace('actions.http.WriterBoundary','actions.http.OperationalWriterBoundary') for m in settings.MIDDLEWARE],ACTIONS_QUOTA_GLOBAL=10000,ACTIONS_QUOTA_IDENTITY=1,ACTIONS_QUOTA_WINDOW_SECONDS=60)
        self.config.enable();self.addCleanup(self.config.disable)
        self.client=Client(HTTP_AUTHORIZATION='Bearer '+self.token)
    def test_statement_timeout_rolls_back_prepare_and_recovers(self):
        from unittest.mock import patch
        from actions.engine import Engine
        from actions.models import Plan,QuotaBucket
        from gestion_joueurs.models import Player
        name='FICTION_TIMEOUT_'+uuid.uuid4().hex
        steps=[{'as':'p','op':'player.create','values':{'name':name,'club':'F','league':'OC','position':'MF','date_of_birth':'2002-01-02'}}]
        original=Engine.prepare
        def slow(engine,key,steps):
            result=original(engine,key,steps)
            with connection.cursor() as c:c.execute('SELECT pg_sleep(0.5)')
            return result
        with override_settings(ACTIONS_STATEMENT_TIMEOUT_MS=80,ACTIONS_LOCK_TIMEOUT_MS=40),patch.object(Engine,'prepare',slow):
            r=self.client.post('/actions/v1/prepare',json.dumps({'key':name,'steps':steps}),content_type='application/json')
        self.assertEqual(r.status_code,503,r.content)
        self.assertEqual(r.json(),{'error':'writer_unavailable'})
        self.assertFalse(Plan.objects.filter(key=name).exists())
        self.assertFalse(Player.objects.filter(name=name).exists())
        self.assertEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).used,1)
        with connection.cursor() as c:c.execute('SELECT 1');self.assertEqual(c.fetchone(),(1,))

    def raw(self):
        import psycopg2
        conn=psycopg2.connect(host='127.0.0.1',port=55440,user='msf_action01_fixture_owner',dbname='msf_action03_fiction')
        self.addCleanup(conn.close)
        return conn

    def test_global_quota_spans_distinct_identities(self):
        from actions.models import QuotaBucket
        from actions.limits import reserve,QuotaExceeded
        used=QuotaBucket.objects.get(key='global').used
        with override_settings(ACTIONS_QUOTA_GLOBAL=used+1,ACTIONS_QUOTA_IDENTITY=10):
            reserve(self.actor.pk)
            with self.assertRaises(QuotaExceeded):reserve(self.actor.pk+1000000)
        self.assertFalse(QuotaBucket.objects.filter(key='actor:'+str(self.actor.pk+1000000)).exists())

    def test_concurrent_connections_never_overspend_identity(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        from actions.limits import reserve,QuotaExceeded
        from actions.models import QuotaBucket
        import threading
        barrier=threading.Barrier(6)
        def run(_):
            try:
                barrier.wait();reserve(self.actor.pk);return 'accepted'
            except QuotaExceeded:return 'denied'
            finally:connections.close_all()
        with override_settings(ACTIONS_QUOTA_GLOBAL=10000,ACTIONS_QUOTA_IDENTITY=3):
            with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(run,range(6)))
        self.assertEqual(results.count('accepted'),3)
        self.assertEqual(results.count('denied'),3)
        self.assertEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).used,3)

    def test_quota_lock_timeout_is_bounded_before_any_business_write(self):
        import time
        from actions.models import QuotaBucket
        other=self.raw()
        with other.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(174651,6)')
        started=time.monotonic()
        try:r=self.client.get('/actions/v1/catalogue')
        finally:other.rollback()
        self.assertEqual(r.status_code,503,r.content)
        self.assertLess(time.monotonic()-started,1.5)
        self.assertFalse(QuotaBucket.objects.filter(key='actor:'+str(self.actor.pk)).exists())
        self.assertEqual(self.client.get('/actions/v1/catalogue').status_code,200)

    def test_database_clock_is_sampled_after_quota_lock(self):
        import threading,time
        from django.db import connections
        from actions.limits import reserve
        from actions.models import QuotaBucket
        other=self.raw()
        with other.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(174651,6)')
        errors=[]
        def run():
            try:reserve(self.actor.pk)
            except Exception as e:errors.append(e)
            finally:connections.close_all()
        thread=threading.Thread(target=run);thread.start();time.sleep(0.08)
        with other.cursor() as c:c.execute('SELECT clock_timestamp()');release=c.fetchone()[0]
        other.commit();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertGreaterEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).window_start,release)

    def test_writer_lock_timeout_preserves_plan_and_recovers(self):
        import time
        from actions.models import Plan,QuotaBucket
        from actions.engine import Engine
        from actions.http import issue_approval
        steps=[{'as':'p','op':'player.create','values':{'name':'FICTION_LOCK_'+uuid.uuid4().hex,'club':'F','league':'OC','position':'MF','date_of_birth':'2002-01-02'}}]
        p=Engine(self.actor.pk).prepare(uuid.uuid4().hex,steps)
        digest=Plan.objects.get(pk=p['id']).digest
        approval=issue_approval(p['id'],self.actor.pk,digest,timezone.now()+timedelta(minutes=1))
        other=self.raw()
        with other.cursor() as c:c.execute('SELECT id FROM actions_plan WHERE id=%s FOR UPDATE',[p['id']])
        started=time.monotonic()
        try:
            with override_settings(ACTIONS_APPROVAL_KEY='FICTION-'+('a'*40),ACTIONS_STATEMENT_TIMEOUT_MS=500,ACTIONS_LOCK_TIMEOUT_MS=60):
                r=self.client.post('/actions/v1/execute',json.dumps({'id':p['id'],'approval':approval}),content_type='application/json')
        finally:other.rollback()
        self.assertEqual(r.status_code,503,r.content)
        self.assertLess(time.monotonic()-started,1.5)
        self.assertEqual(Plan.objects.get(pk=p['id']).state,'prepared')
        self.assertEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).used,1)
        with connection.cursor() as c:c.execute('SELECT 1');self.assertEqual(c.fetchone(),(1,))

    def test_execute_timeout_rolls_back_real_player_and_quota_stays_spent(self):
        from unittest.mock import patch
        from actions.engine import Engine
        from actions.models import Plan,QuotaBucket
        from actions.http import issue_approval
        from gestion_joueurs.models import Player
        name='FICTION_EXEC_TIMEOUT_'+uuid.uuid4().hex
        steps=[{'as':'p','op':'player.create','values':{'name':name,'club':'F','league':'OC','position':'MF','date_of_birth':'2002-01-02'}}]
        p=Engine(self.actor.pk).prepare(uuid.uuid4().hex,steps)
        approval=issue_approval(p['id'],self.actor.pk,Plan.objects.get(pk=p['id']).digest,timezone.now()+timedelta(minutes=1))
        original=Engine._apply
        def slow(engine,steps,actor):
            result=original(engine,steps,actor)
            with connection.cursor() as c:c.execute('SELECT pg_sleep(0.5)')
            return result
        with override_settings(ACTIONS_STATEMENT_TIMEOUT_MS=80,ACTIONS_LOCK_TIMEOUT_MS=40),patch.object(Engine,'_apply',slow):
            r=self.client.post('/actions/v1/execute',json.dumps({'id':p['id'],'approval':approval}),content_type='application/json')
        self.assertEqual(r.status_code,503,r.content)
        self.assertFalse(Player.objects.filter(name=name).exists())
        self.assertEqual(Plan.objects.get(pk=p['id']).state,'prepared')
        self.assertEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).used,1)
        with override_settings(ACTIONS_QUOTA_IDENTITY=3):
            retry=self.client.post('/actions/v1/execute',json.dumps({'id':p['id'],'approval':approval}),content_type='application/json')
            self.assertEqual(retry.status_code,200,retry.content)
            self.assertEqual(retry.json()['state'],'succeeded')
            second=self.client.post('/actions/v1/execute',json.dumps({'id':p['id'],'approval':approval}),content_type='application/json')
            self.assertEqual(second.json(),retry.json())
        self.assertEqual(Player.objects.filter(name=name).count(),1)
        other=self.raw()
        with other.cursor() as c:
            c.execute('SELECT state FROM actions_plan WHERE id=%s',[p['id']]);self.assertEqual(c.fetchone(),('succeeded',))
            c.execute('SELECT count(*) FROM gestion_joueurs_player WHERE name=%s',[name]);self.assertEqual(c.fetchone(),(1,))

    def test_caller_guards_prepare_execute_preserve_timeouts_and_quota(self):
        from actions.models import QuotaBucket
        for manual in (False,True):
            if manual:connection.set_autocommit(False)
            else:atomic=transaction.atomic();atomic.__enter__()
            try:
                with connection.cursor() as c:
                    c.execute("SET LOCAL statement_timeout='730ms'; SET LOCAL lock_timeout='510ms'")
                for route in ('prepare','execute'):
                    r=self.client.post('/actions/v1/'+route,'{}',content_type='application/json')
                    self.assertEqual(r.status_code,409,r.content)
                with connection.cursor() as c:
                    c.execute('SHOW statement_timeout');self.assertEqual(c.fetchone(),('730ms',))
                    c.execute('SHOW lock_timeout');self.assertEqual(c.fetchone(),('510ms',))
                    c.execute('SELECT 1');self.assertEqual(c.fetchone(),(1,))
                self.assertFalse(QuotaBucket.objects.filter(key='actor:'+str(self.actor.pk)).exists())
            finally:
                if manual:connection.rollback();connection.set_autocommit(True)
                else:transaction.set_rollback(True);atomic.__exit__(None,None,None)

    def test_timeout_settings_are_local_to_owned_transaction(self):
        with connection.cursor() as c:
            c.execute('SHOW statement_timeout');statement=c.fetchone()
            c.execute('SHOW lock_timeout');lock=c.fetchone()
        self.assertEqual(self.client.get('/actions/v1/catalogue').status_code,200)
        with connection.cursor() as c:
            c.execute('SHOW statement_timeout');self.assertEqual(c.fetchone(),statement)
            c.execute('SHOW lock_timeout');self.assertEqual(c.fetchone(),lock)

    def test_quota_window_rollover_uses_database_time(self):
        from actions.limits import reserve
        from actions.models import QuotaBucket
        reserve(self.actor.pk)
        with connection.cursor() as c:
            c.execute("UPDATE actions_quotabucket SET window_start=clock_timestamp()-interval '61 seconds' WHERE key=%s",['actor:'+str(self.actor.pk)])
        reserve(self.actor.pk)
        self.assertEqual(QuotaBucket.objects.get(key='actor:'+str(self.actor.pk)).used,1)

    def test_identity_quota_is_shared_between_http_clients(self):
        first=self.client.get('/actions/v1/catalogue')
        second=Client(HTTP_AUTHORIZATION='Bearer '+self.token).get('/actions/v1/catalogue')
        self.assertEqual(first.status_code,200,first.content)
        self.assertEqual(second.status_code,429,second.content)
        self.assertEqual(second.json(),{'error':'quota_exceeded'})
        self.assertEqual(second['Cache-Control'],'no-store')
