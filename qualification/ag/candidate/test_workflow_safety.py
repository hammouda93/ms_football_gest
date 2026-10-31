from test_workflow import *
from unittest.mock import patch

class SafetyTests(WorkflowTests):
    def test_transition_and_patch_same_video_closed(self):
        steps=self.steps()+[{'as':'patch','op':'video.amend','values':{'id':self.video.pk,'info':'FICTION'}}]
        with self.assertRaisesRegex(ValueError,'duplicate_target'):self.engine.prepare(uuid.uuid4().hex,steps)
    def test_preexisting_workflow_validation_does_not_change_previous_stage(self):
        VideoWorkflow.objects.create(video=self.video,stage='awaiting_media',progress=20)
        steps=[{'as':'w','op':'video.workflow.transition','values':{'id':self.video.pk,'stage':'blocked','priority':'normal','progress':0,'next_action':'','blocked_reason':'FICTION'}}]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded',r)
        self.assertEqual(VideoActivity.objects.get(video=self.video).metadata,{'from':'awaiting_media','to':'blocked'})
    def test_scopes_before_object_reads_prepare_and_execute(self):
        from django.test import Client
        from actions.http import issue_approval
        from actions.workflow import ProductionTransition
        p=self.engine.prepare(uuid.uuid4().hex,self.steps());plan=Plan.objects.get(pk=p['id'])
        token=uuid.uuid4().hex
        cred={'actor':self.admin.pk,'scopes':['prepare','execute'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary']):
            client=Client(HTTP_AUTHORIZATION='Bearer '+token)
            approval=issue_approval(p['id'],self.admin.pk,plan.digest,timezone.now()+timedelta(minutes=2))
            with patch.object(ProductionTransition,'target',side_effect=AssertionError('OBJECT BEFORE SCOPE')):
                for route,payload in [('prepare',{'key':uuid.uuid4().hex,'steps':self.steps()}),('execute',{'id':p['id'],'approval':approval})]:
                    response=client.post('/actions/v1/'+route,data=json.dumps(payload),content_type='application/json');self.assertEqual((response.status_code,response.json()),(403,{'error':'scope_denied'}))
    def test_external_effects_guard_denies_network(self):
        import socket
        from actions.workflow import external_effects_closed
        with external_effects_closed(),self.assertRaisesRegex(PermissionError,'workflow_external_effect_forbidden'):
            with socket.socket() as s:s.connect(('127.0.0.1',55573))
    def test_same_stage_updates_no_activity(self):
        VideoWorkflow.objects.create(video=self.video,stage='awaiting_media',progress=20)
        steps=[{'as':'w','op':'video.workflow.transition','values':{'id':self.video.pk,'stage':'awaiting_media','priority':'high','progress':21,'next_action':'FICTION','blocked_reason':''}}]
        p=self.engine.prepare(uuid.uuid4().hex,steps);r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded');self.assertEqual(r['effects']['activities'],[])
    def test_invalid_blocked_reason_rejected_without_write(self):
        steps=[{'as':'w','op':'video.workflow.transition','values':{'id':self.video.pk,'stage':'blocked','priority':'normal','progress':0,'next_action':'','blocked_reason':''}}]
        with self.assertRaisesRegex(ValueError,'invalid_transition_form'):self.engine.prepare(uuid.uuid4().hex,steps)
        self.assertFalse(VideoWorkflow.objects.filter(video=self.video).exists())
