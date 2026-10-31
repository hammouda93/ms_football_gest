from test_workflow import *
from unittest.mock import patch

class MoreTests(WorkflowTests):
    def test_status_noop_creates_no_effects(self):
        p=self.engine.prepare(uuid.uuid4().hex,self.steps('pending'))
        r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded')
        self.assertTrue(all(not v for v in r['effects'].values()))
    def test_delivered_explicitly_closed(self):
        with self.assertRaisesRegex(ValueError,'delivery_closed'):self.engine.prepare(uuid.uuid4().hex,self.steps('delivered'))
    def test_problematic_excluded_active_and_sync_exact(self):
        VideoWorkflow.objects.create(video=self.video,stage='awaiting_media',progress=20)
        p=self.engine.prepare(uuid.uuid4().hex,self.steps('problematic'))
        preview=Plan.objects.get(pk=p['id']).snapshots['__preview__']['transitions'][0]
        self.assertTrue(preview['outsideActiveProduction'])
        self.assertEqual(self.engine.execute(p['id'])['state'],'succeeded')
        self.assertEqual(VideoWorkflow.objects.get(video=self.video).stage,'blocked')
        self.assertEqual(list(VideoActivity.objects.filter(video=self.video).values('kind','visibility','message','metadata','created_by_id')),preview['activities'])
    def test_completed_notifications_exact(self):
        p=self.engine.prepare(uuid.uuid4().hex,self.steps('completed'))
        preview=Plan.objects.get(pk=p['id']).snapshots['__preview__']['transitions'][0]
        r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded',r)
        rows=list(Notification.objects.filter(pk__in=r['effects']['notifications']).order_by('user_id').values('user_id','message','notification_type','video_id','player_id','sent_by_id','is_read'))
        self.assertEqual(rows,preview['notifications'])
    def test_editor_object_permission_and_terminal_guard(self):
        e=Engine(self.editor.pk)
        p=e.prepare(uuid.uuid4().hex,self.steps('completed_collab'));self.assertEqual(e.execute(p['id'])['state'],'succeeded')
        with self.assertRaisesRegex(ValueError,'invalid_transition_form'):e.prepare(uuid.uuid4().hex,self.steps('completed'))
        other=User.objects.create(username='FICTION_OTHER_'+uuid.uuid4().hex);VideoEditor.objects.create(user=other)
        with self.assertRaisesRegex(PermissionError,'object_permission_denied'):Engine(other.pk).prepare(uuid.uuid4().hex,self.steps())
    def test_dependency_conflict(self):
        p=self.engine.prepare(uuid.uuid4().hex,self.steps());Invoice.objects.filter(pk=self.invoice.pk).update(amount_paid=1)
        r=self.engine.execute(p['id']);self.assertEqual((r['state'],r['error']),('failed','conflict'))
        self.video.refresh_from_db();self.assertEqual(self.video.status,'pending')
    def test_duplicate_transition_target_closed(self):
        steps=self.steps()+[dict(self.steps('problematic')[0],**{'as':'second'})]
        with self.assertRaisesRegex(ValueError,'duplicate_target'):self.engine.prepare(uuid.uuid4().hex,steps)
    def test_prepare_never_calls_business_save(self):
        with patch.object(Video,'save',side_effect=AssertionError('SAVE')),patch.object(VideoWorkflow,'save',side_effect=AssertionError('SAVE')):self.engine.prepare(uuid.uuid4().hex,self.steps())
    def test_atomic_later_failure_rolls_back_transition(self):
        from actions.workflow import WORKFLOWS
        p=self.engine.prepare(uuid.uuid4().hex,self.steps());adapter=WORKFLOWS['video.status.transition'];original=adapter.apply
        def fail(*args,**kwargs):original(*args,**kwargs);raise ValueError('late_failure')
        with patch.object(adapter,'apply',side_effect=fail):r=self.engine.execute(p['id'])
        self.assertEqual((r['state'],r['error']),('failed','late_failure'))
        self.video.refresh_from_db();self.assertEqual(self.video.status,'pending')
        self.assertEqual(VideoStatusHistory.objects.filter(video=self.video).count(),1)
    def test_socket_http_consent_scopes_status_readback(self):
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from actions.http import issue_approval
        token=uuid.uuid4().hex
        credential={'actor':self.admin.pk,'scopes':['prepare','execute','status','catalogue','op:video.status.transition'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        class Quiet(WSGIRequestHandler):
            def log_message(self,*args):pass
        def request(route,data):
            req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=5) as response:return response.status,json.load(response)
            except HTTPError as response:return response.code,json.load(response)
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():credential},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet);thread=threading.Thread(target=server.serve_forever);thread.start()
            try:
                code,p=request('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()});self.assertEqual(code,200,p)
                code,denied=request('execute',{'id':p['id'],'approval':'invalid'});self.assertEqual(code,403,denied)
                approval=issue_approval(p['id'],self.admin.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                code,r=request('execute',{'id':p['id'],'approval':approval});self.assertEqual((code,r['state']),(200,'succeeded'),r)
                self.assertEqual(request('execute',{'id':p['id'],'approval':approval})[1],r)
                self.assertEqual(request('status',{'id':p['id']})[1],r)
                self.video.refresh_from_db();self.assertEqual(self.video.status,'in_progress')
                credential['scopes'].remove('op:video.status.transition')
                self.assertEqual(request('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()}),(403,{'error':'scope_denied'}))
            finally:server.shutdown();server.server_close();thread.join(5)
