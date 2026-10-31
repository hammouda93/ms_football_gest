"""Bounded regressions for review-integration SEC-01 and LOG-01."""
import unittest,uuid,json,hashlib,threading,importlib.util
from datetime import timedelta,date
from pathlib import Path
from django.contrib.auth.models import User
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from actions.engine import Engine
from actions.models import Plan
from actions.http import issue_approval
from client_portal.models import Organization
from gestion_joueurs.models import Player
ROOT=Path(__file__).resolve().parent

class FinalTests(unittest.TestCase):
    def setUp(self):
        self.actor=User.objects.create(username='FICTION_FINAL_'+uuid.uuid4().hex,is_active=True,is_superuser=True)
        self.engine=Engine(self.actor.pk)

    def test_execute_scopes_before_objects_all_target_states_socket(self):
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        org=Organization.objects.create(name='FICTION_FINAL_SCOPE',kind='agent')
        p=self.engine.prepare(uuid.uuid4().hex,[{'as':'o','op':'organization.details.amend','values':{'id':org.pk,'name':'DENIED'}}])
        saved=Plan.objects.get(pk=p['id']);before=(saved.digest,saved.snapshots,saved.state)
        token=uuid.uuid4().hex;queries=[];attempts=[]
        credential={'actor':self.actor.pk,'scopes':['execute'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        def trace(execute,sql,params,many,context):
            queries.append(sql)
            return execute(sql,params,many,context)
        class Quiet(WSGIRequestHandler):
            def log_message(self,*args):pass
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():credential},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
            approval=issue_approval(saved.pk,self.actor.pk,saved.digest,timezone.now()+timedelta(minutes=2))
            app=get_wsgi_application()
            def traced_app(environ,start_response):
                with connection.execute_wrapper(trace):return app(environ,start_response)
            server=make_server('127.0.0.1',55573,traced_app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for state in ['active','inactive','missing']:
                    if state=='inactive':Organization.objects.filter(pk=org.pk).update(is_active=False)
                    if state=='missing':Organization.objects.filter(pk=org.pk).delete()
                    queries.clear()
                    req=Request('http://127.0.0.1:55573/actions/v1/execute',data=json.dumps({'id':p['id'],'approval':approval}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                    try:
                        with urlopen(req,timeout=5) as r:status,body=r.status,json.load(r)
                    except HTTPError as r:status,body=r.code,json.load(r)
                    reads=[q for q in queries if q.lstrip().upper().startswith('SELECT') and 'client_portal_organization' in q]
                    attempts.append({'state':state,'http':status,'body':body,'target_selects':len(reads)})
            finally:
                server.shutdown();server.server_close();thread.join(5)
                self.assertFalse(thread.is_alive())
        (ROOT/'security-probe-result.json').write_text(json.dumps(attempts,indent=2))
        saved.refresh_from_db();self.assertEqual((saved.digest,saved.snapshots,saved.state),before)
        self.assertEqual(attempts,[{'state':s,'http':403,'body':{'error':'scope_denied'},'target_selects':0} for s in ['active','inactive','missing']])

    def test_original_prepared_plan_executes_candidate_exact_readback(self):
        spec=importlib.util.spec_from_file_location('actions.final_original_engine',ROOT/'original/actions/engine.py')
        original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
        player=Player.objects.create(name='FICTION_LEGACY_'+uuid.uuid4().hex,club='BEFORE',league='OC',position='MF',date_of_birth=date(2002,1,2))
        steps=[{'as':'p','op':'player.amend','values':{'id':player.pk,'club':'AFTER'}}]
        p=original.Engine(self.actor.pk).prepare(uuid.uuid4().hex,steps)
        saved=Plan.objects.get(pk=p['id'])
        self.assertNotIn('changes',saved.snapshots['__preview__'])
        snapshot=saved.snapshots;digest=saved.digest
        self.assertEqual(self.engine.proposal_digest(steps,snapshot),digest)
        before=Player.objects.values().get(pk=player.pk)
        result=self.engine.execute(saved.pk)
        self.assertEqual(result['state'],'succeeded',result)
        saved.refresh_from_db();self.assertEqual((saved.snapshots,saved.digest),(snapshot,digest))
        after=Player.objects.values().get(pk=player.pk)
        self.assertEqual(after,dict(before,club='AFTER'))
        self.assertEqual(self.engine.execute(saved.pk),result)
        (ROOT/'legacy-result.json').write_text(json.dumps({'id':str(saved.pk),'digest':digest,'snapshots':snapshot,'player':player.pk,'expected_row':after,'original_engine_sha256':hashlib.sha256((ROOT/'original/actions/engine.py').read_bytes()).hexdigest(),'state':result['state']},default=str,indent=2))
