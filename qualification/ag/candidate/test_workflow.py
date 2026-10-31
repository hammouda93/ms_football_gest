import unittest,uuid,json,hashlib,threading
from datetime import date,timedelta
from django.contrib.auth.models import User
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from actions.engine import Engine
from actions.models import Plan
from gestion_joueurs.models import Player,Video,VideoEditor,Invoice,VideoStatusHistory,Notification
from client_portal.models import VideoWorkflow,VideoActivity

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.admin=User.objects.create(username='FICTION_WFA_'+uuid.uuid4().hex,is_superuser=True)
        self.editor=User.objects.create(username='FICTION_WFE_'+uuid.uuid4().hex)
        self.ve=VideoEditor.objects.create(user=self.editor)
        self.player=Player.objects.create(name='FICTION_WF',club='CLUB',league='OC',position='MF',date_of_birth=date(2002,1,2))
        self.video=Video.objects.create(player=self.player,editor=self.ve,status='pending',total_payment=300,advance_payment=0,season='2025/2026',deadline=date(2030,1,1))
        self.invoice=Invoice.objects.create(video=self.video,total_amount=300,amount_paid=0,status='unpaid',created_by=self.admin)
        self.engine=Engine(self.admin.pk)
    def steps(self,status='in_progress'):
        return [{'as':'transition','op':'video.status.transition','values':{'id':self.video.pk,'status':status}}]
    def test_status_vertical_prepare_execute_readback(self):
        before=VideoStatusHistory.objects.filter(video=self.video).count()
        p=self.engine.prepare(uuid.uuid4().hex,self.steps())
        plan=Plan.objects.get(pk=p['id'])
        self.assertIn('transitions',plan.snapshots['__preview__'])
        self.video.refresh_from_db();self.assertEqual(self.video.status,'pending')
        self.assertEqual(VideoStatusHistory.objects.filter(video=self.video).count(),before)
        result=self.engine.execute(p['id']);self.assertEqual(result['state'],'succeeded',result)
        self.video.refresh_from_db();self.assertEqual(self.video.status,'in_progress')
        history=VideoStatusHistory.objects.filter(video=self.video).latest('changed_at')
        self.assertEqual((history.status,history.created_by_id),('in_progress',self.admin.pk))
        self.assertEqual(self.engine.execute(p['id']),result)

    def test_editor_cannot_use_legacy_amendment(self):
        with self.assertRaisesRegex(PermissionError,'permission_denied'):
            Engine(self.editor.pk).prepare(uuid.uuid4().hex,[{'as':'p','op':'player.amend','values':{'id':self.player.pk,'club':'DENIED'}}])

    def test_workflow_vertical_effects_readback(self):
        steps=[{'as':'w','op':'video.workflow.transition','values':{'id':self.video.pk,'stage':'blocked','priority':'urgent','progress':0,'next_action':'Attendre','blocked_reason':'FICTION motif'}}]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        preview=Plan.objects.get(pk=p['id']).snapshots['__preview__']['transitions'][0]
        self.assertFalse(VideoWorkflow.objects.filter(video=self.video).exists())
        result=self.engine.execute(p['id']);self.assertEqual(result['state'],'succeeded',result)
        wf=VideoWorkflow.objects.get(video=self.video)
        self.assertEqual((wf.stage,wf.priority,wf.progress,wf.blocked_reason),('blocked','urgent',0,'FICTION motif'))
        activities=list(VideoActivity.objects.filter(video=self.video).values('kind','visibility','message','metadata','created_by_id'))
        self.assertEqual(activities,preview['activities'])
        self.assertEqual(len(result['effects']['activities']),1)
        self.video.refresh_from_db();self.assertEqual(self.video.status,'pending')
