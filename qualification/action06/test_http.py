import unittest,uuid,json,hashlib,secrets
from datetime import timedelta
from django.test import Client,override_settings
from django.utils import timezone
from test_actions import ActionsTests

class HTTPTests(unittest.TestCase):
    plan=ActionsTests.plan
    engine=ActionsTests.engine
    tearDown=ActionsTests.tearDown
    def setUp(self):
        ActionsTests.setUp(self)
        self.token=secrets.token_urlsafe(32)
        self.credentials={hashlib.sha256(self.token.encode()).hexdigest():{'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status','op:player.create','op:organization.link','op:video.order','op:player.amend','op:video.amend'],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False}}
        self.config=override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS=self.credentials,ACTIONS_APPROVAL_KEY='FICTION-'+secrets.token_hex(32))
        self.config.enable();self.addCleanup(self.config.disable)
        self.client=Client(enforce_csrf_checks=True,HTTP_AUTHORIZATION='Bearer '+self.token)
    def post(self,path,data):
        return self.client.post('/actions/v1/'+path,json.dumps(data),content_type='application/json')
    def test_effect_receipt_contains_exact_signal_records(self):
        from django.contrib.auth.models import User
        from gestion_joueurs.models import VideoEditor,VideoStatusHistory,Notification
        other=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex)
        editor=VideoEditor.objects.create(user=other)
        steps=self.plan();steps[-1]['values']['editor']=editor.pk
        p=self.post('prepare',{'key':self.key,'steps':steps}).json()
        from actions.http import issue_approval
        a=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
        r=self.post('execute',{'id':p['id'],'approval':a}).json()
        video=r['results']['order']
        history=VideoStatusHistory.objects.get(video_id=video)
        notification=Notification.objects.get(video_id=video)
        self.assertEqual(history.created_by_id,self.actor.pk)
        self.assertEqual((notification.user_id,notification.sent_by_id),(other.pk,self.actor.pk))
        self.assertEqual(r['effects'],{'history':[history.pk],'notifications':[notification.pk],'invoices':[__import__('gestion_joueurs.models',fromlist=['Invoice']).Invoice.objects.get(video_id=video).pk]})
        self.assertEqual(self.post('execute',{'id':p['id'],'approval':a}).json(),r)
    def test_malformed_inputs_are_json_not_500(self):
        cases=[{'key':'x','steps':[{'as':'p','op':[],'values':{}}]}, {'key':'x','steps':[{'as':'p','op':'player.create','values':{'name':{'ref':[]}}}]}]
        for data in cases:
            r=self.post('prepare',data);self.assertEqual(r.status_code,400);self.assertEqual(r['Cache-Control'],'no-store')
        for value in [[],{},True,1,'invalid']:
            r=self.post('status',{'id':value});self.assertEqual(r.status_code,400)
    def test_negative_auth_approval_matrix_and_session_isolation(self):
        from unittest.mock import patch
        from actions.http import issue_approval
        from gestion_joueurs.models import Player
        from django.contrib.auth.models import User
        before=Player.objects.count()
        p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
        c=next(iter(self.credentials.values()))
        good=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
        cases=[good+'x',issue_approval(p['id'],self.actor.pk,'0'*64,timezone.now()+timedelta(minutes=2)),issue_approval(p['id'],self.actor.pk+1,p['digest'],timezone.now()+timedelta(minutes=2)),issue_approval(str(uuid.uuid4()),self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2)),issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()-timedelta(seconds=1))]
        for approval in cases:self.assertEqual(self.post('execute',{'id':p['id'],'approval':approval}).status_code,403)
        for changes in [{'revoked':True},{'expires':(timezone.now()-timedelta(seconds=1)).isoformat()},{'expires':'2026-01-01T00:00:00'},{'scopes':[]},{'extra':'not allowed'}]:
            old=dict(c);c.update(changes)
            self.assertEqual(self.client.get('/actions/v1/catalogue').status_code,403)
            c.clear();c.update(old)
        with override_settings(ACTIONS_ENABLED=False):self.assertEqual(self.client.get('/actions/v1/catalogue').status_code,403)
        for token in ['', 'Bearer reader-fixture','Basic ignored']:
            self.assertEqual(Client(HTTP_AUTHORIZATION=token).get('/actions/v1/catalogue').status_code,403)
        User.objects.filter(pk=self.actor.pk).update(is_superuser=False)
        self.assertEqual(self.post('execute',{'id':p['id'],'approval':good}).status_code,403)
        User.objects.filter(pk=self.actor.pk).update(is_superuser=True)
        self.client.cookies['sessionid']='FICTION_stale'
        with patch('django.contrib.sessions.backends.db.SessionStore.load',side_effect=AssertionError('session touched')):
            self.assertEqual(self.client.get('/actions/v1/catalogue').status_code,200)
            self.assertEqual(self.client.get('/actions/v1/missing').status_code,404)
        self.assertEqual(Player.objects.count(),before)
    def test_operation_scope_required_on_prepare_and_execute(self):
        cred=next(iter(self.credentials.values()))
        cred['scopes'].remove('op:video.order')
        self.assertEqual(self.post('prepare',{'key':self.key,'steps':self.plan()}).status_code,403)
        cred['scopes'].append('op:video.order')
        p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
        from actions.http import issue_approval
        a=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
        cred['scopes'].remove('op:video.order')
        self.assertEqual(self.post('execute',{'id':p['id'],'approval':a}).status_code,403)
    def test_action_signal_actor_is_exact_and_cleared(self):
        from gestion_joueurs.utils import get_current_user,set_current_user
        from gestion_joueurs.models import VideoStatusHistory,Notification
        set_current_user(None)
        p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
        from actions.http import issue_approval
        a=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
        r=self.post('execute',{'id':p['id'],'approval':a}).json()
        h=VideoStatusHistory.objects.get(video_id=r['results']['order'])
        self.assertEqual(h.created_by_id,self.actor.pk)
        self.assertIsNone(get_current_user())
        self.assertFalse(Notification.objects.filter(video_id=h.video_id).exists())
    def test_http_lifecycle(self):
        r=self.client.get('/actions/v1/catalogue');self.assertEqual(r.status_code,200,r.content)
        self.assertIn('video.order',r.json()['catalogue'])
        r=self.post('prepare',{'key':self.key,'steps':self.plan()});self.assertEqual(r.status_code,200,r.content)
        p=r.json();self.assertIn('digest',p);self.assertFalse(__import__('gestion_joueurs.models',fromlist=['Player']).Player.objects.filter(name=self.name).exists())
        self.assertEqual(self.post('execute',{'id':p['id']}).status_code,403)
        from actions.http import issue_approval
        approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
        r=self.post('execute',{'id':p['id'],'approval':approval});self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['state'],'succeeded')
        self.assertEqual(self.post('execute',{'id':p['id'],'approval':approval}).json(),r.json())
        self.assertEqual(self.post('status',{'id':p['id']}).json(),r.json())
