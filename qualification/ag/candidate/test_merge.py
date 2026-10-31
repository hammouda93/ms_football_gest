"""Cross-family integration assertions; no new business capability."""
import unittest
from actions.registry import catalogue,LEGACY,SIMPLE
from actions.declarative import DEFINITIONS
from actions.workflow import WORKFLOWS
class MergeTests(unittest.TestCase):
    def test_declarative_creation_prepare_has_no_id_requirement(self):
        from test_declarative import DeclarativeTests
        import uuid
        t=DeclarativeTests();t.setUp()
        result=None
        try:result=t.engine.prepare(uuid.uuid4().hex,[t.step('organization.profile.create',{'name':'FICTION_MERGE_'+uuid.uuid4().hex,'kind':'club'})])
        except KeyError:pass
        self.assertIsNotNone(result,'reviewed create contract must prepare without id')
    def test_mixed_profile_and_transition_real_http_exact_commit(self):
        import uuid,json,hashlib,threading
        from pathlib import Path
        from datetime import timedelta
        from django.utils import timezone
        from django.test import override_settings
        from django.core.wsgi import get_wsgi_application
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from urllib.request import Request,urlopen
        from actions.http import issue_approval
        from actions.models import Plan
        from test_workflow import WorkflowTests
        from test_wf01 import business_rows,assert_effects
        from gestion_joueurs.models import Player
        from client_portal.models import Organization
        records=[]
        for kind in ('status','workflow'):
            t=WorkflowTests();t.setUp()
            steps=[{'as':'org','op':'organization.profile.create','values':{'name':'FICTION_MIXED_'+uuid.uuid4().hex,'kind':'club'}},{'as':'profile','op':'player.profile.amend','values':{'id':t.player.pk,'club':'MIXED_CLUB'}}]
            steps+=t.steps() if kind=='status' else [{'as':'w','op':'video.workflow.transition','values':{'id':t.video.pk,'stage':'blocked','priority':'urgent','progress':0,'next_action':'Attendre','blocked_reason':'FICTION_MIXED'}}]
            token=uuid.uuid4().hex
            cred={'actor':t.admin.pk,'scopes':['catalogue','prepare','execute','status',*['op:'+s['op'] for s in steps]],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
            class Quiet(WSGIRequestHandler):
                def log_message(self,*a):pass
            with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
                server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet)
                thread=threading.Thread(target=server.serve_forever);thread.start()
                try:
                    def call(route,data=None):
                        request=Request('http://127.0.0.1:55573/actions/v1/'+route,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                        with urlopen(request,timeout=10) as response:return json.load(response)
                    self.assertEqual(set(call('catalogue')['catalogue']),{s['op'] for s in steps})
                    before={t.video.pk:business_rows(t.video.pk)}
                    old_player=Player.objects.values().get(pk=t.player.pk);org_count=Organization.objects.count()
                    key=uuid.uuid4().hex;p=call('prepare',{'key':key,'steps':steps})
                    self.assertEqual(Player.objects.values().get(pk=t.player.pk),old_player)
                    self.assertEqual(business_rows(t.video.pk),before[t.video.pk]);self.assertEqual(Organization.objects.count(),org_count)
                    plan=Plan.objects.get(pk=p['id'])
                    approval=issue_approval(plan.pk,t.admin.pk,plan.digest,timezone.now()+timedelta(minutes=2))
                    result=call('execute',{'id':p['id'],'approval':approval});self.assertEqual(result['state'],'succeeded',result)
                    self.assertEqual(call('execute',{'id':p['id'],'approval':approval}),result)
                    self.assertEqual(call('status',{'id':p['id']}),result)
                    self.assertEqual(call('prepare',{'key':key,'steps':steps})['id'],p['id'])
                    assert_effects(self,plan,result,before)
                    profile=plan.snapshots['__preview__']['changes'][1]
                    expected=dict(old_player,**profile['new'])
                    self.assertEqual(Player.objects.values().get(pk=t.player.pk),expected)
                    org=Organization.objects.values().get(pk=result['results']['org'])
                    for field,value in plan.snapshots['__preview__']['changes'][0]['new'].items():self.assertEqual(json.loads(json.dumps(org[field],default=str)),value)
                    records.append({'kind':'mixed_'+kind,'video':t.video.pk,'plan':p['id'],'result':result,'readback':business_rows(t.video.pk),'player':expected,'organization':org,'preview':plan.snapshots['__preview__']})
                finally:server.shutdown();server.server_close();thread.join(5)
        Path(__file__).with_name('mixed-missions.json').write_text(json.dumps(records,default=str,indent=2))
    def test_editor_cannot_prepare_or_execute_declarative_even_with_workflow(self):
        from test_workflow import WorkflowTests
        from actions.engine import Engine
        from gestion_joueurs.models import Player
        import uuid
        t=WorkflowTests();t.setUp()
        steps=[{'as':'p','op':'player.profile.amend','values':{'id':t.player.pk,'club':'DENIED'}}]+t.steps()
        old=Player.objects.values().get(pk=t.player.pk)
        with self.assertRaisesRegex(PermissionError,'permission_denied'):Engine(t.editor.pk).prepare(uuid.uuid4().hex,steps)
        p=t.engine.prepare(uuid.uuid4().hex,steps)
        from django.contrib.auth.models import User
        User.objects.filter(pk=t.admin.pk).update(is_superuser=False)
        from gestion_joueurs.models import VideoEditor
        VideoEditor.objects.create(user_id=t.admin.pk)
        with self.assertRaisesRegex(PermissionError,'permission_denied'):t.engine.execute(p['id'])
        self.assertEqual(Player.objects.values().get(pk=t.player.pk),old)
    def test_same_video_amend_and_transition_refused_by_existing_contract(self):
        from test_workflow import WorkflowTests
        import uuid
        t=WorkflowTests();t.setUp()
        steps=[{'as':'v','op':'video.amend','values':{'id':t.video.pk,'info':'FICTION'}}]+t.steps()
        with self.assertRaisesRegex(ValueError,'duplicate_target'):t.engine.prepare(uuid.uuid4().hex,steps)
    def test_registry_contains_exact_union_of_reviewed_contracts(self):
        self.assertEqual(set(catalogue()),set(LEGACY)|set(SIMPLE)|set(DEFINITIONS)|set(WORKFLOWS))
        for op,adapter in DEFINITIONS.items():self.assertEqual(catalogue()[op],adapter.contract())
        for op,adapter in WORKFLOWS.items():self.assertEqual(catalogue()[op],adapter.contract())
