"""Real socket WF-01 refusals and exact successful effect readback."""
import json,hashlib,uuid,threading,unittest
from datetime import timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from wsgiref.simple_server import make_server,WSGIRequestHandler
from django.test import override_settings
from django.utils import timezone
from django.core.wsgi import get_wsgi_application
from actions.http import issue_approval
from actions.models import Plan
from test_wf01 import WF01Tests,business_rows,assert_effects

class HttpWF01Tests(unittest.TestCase):
    setUp=WF01Tests.setUp
    steps=WF01Tests.steps
    tie=WF01Tests.tie
    def test_socket_ambiguity_at_prepare_and_execute_and_exact_success(self):
        token=uuid.uuid4().hex
        cred={'actor':self.admin.pk,'scopes':['prepare','execute','status','op:video.status.transition'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        class Quiet(WSGIRequestHandler):
            def log_message(self,*args):pass
        def call(route,data):
            req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=5) as r:return r.status,json.load(r)
            except HTTPError as r:return r.code,json.load(r)
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet);thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                before={self.video.pk:business_rows(self.video.pk)}
                code,p=call('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()});self.assertEqual(code,200,p)
                approval=issue_approval(p['id'],self.admin.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                code,r=call('execute',{'id':p['id'],'approval':approval});self.assertEqual((code,r['state']),(200,'succeeded'))
                assert_effects(self,Plan.objects.get(pk=p['id']),r,before)
                self.assertEqual(call('status',{'id':p['id']}),(200,r))
                # New fixture, then a tie introduced after approval.
                self.setUp()
                cred['actor']=self.admin.pk
                code,p=call('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()});self.assertEqual(code,200,p)
                approval=issue_approval(p['id'],self.admin.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                self.tie();before=business_rows(self.video.pk)
                self.assertEqual(call('execute',{'id':p['id'],'approval':approval}),(400,{'error':'workflow_history_ambiguous'}))
                self.assertEqual(call('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()}),(400,{'error':'workflow_history_ambiguous'}))
                self.assertEqual(business_rows(self.video.pk),before)
                self.assertEqual(Plan.objects.get(pk=p['id']).state,'prepared')
            finally:server.shutdown();server.server_close();thread.join(5)
