import uuid,json,hashlib,unittest
from test_actions import ActionsTests
from django.apps import apps
from django.core import mail
from actions.models import Plan,Audit

class CompatibilityTests(ActionsTests):
    # Reuse fixture and plan builders, not inherited historical assertions.
    def footprint(self):
        return {m._meta.label:json.dumps(list(m.objects.order_by('pk').values()),sort_keys=True,default=str) for m in apps.get_models() if m._meta.app_label in {'gestion_joueurs','client_portal','prospects','sportsbase_data'}}
    def refused(self,steps,code):
        before=self.footprint();plans=Plan.objects.count();outbox=len(getattr(mail,'outbox',[]));key=uuid.uuid4().hex
        with self.assertRaisesRegex(ValueError,'^'+code+'$'):
            self.engine().prepare(key,steps)
        self.assertEqual(Plan.objects.count(),plans)
        self.assertEqual(self.footprint(),before)
        self.assertEqual(len(getattr(mail,'outbox',[])),outbox)
        self.assertTrue(Audit.objects.filter(actor_id=self.actor.pk,event='refused',code=code).exists())
    def test_positive_advance_refused_by_real_prepare_before_plan(self):
        steps=self.plan();steps[-1]['values']['advance_payment']='1'
        self.refused(steps,'payment_not_supported')

    def test_manual_deadline_refused_by_real_prepare_before_plan(self):
        steps=self.plan();steps[-1]['values']['deadline_from_whatsapp']=False
        self.refused(steps,'automatic_deadline_required')

    def test_invalid_video_form_refused_before_plan(self):
        steps=self.plan();steps[-1]['values']['season']='INVALID'
        self.refused(steps,'invalid_video')

    def test_preview_uses_real_form_date_normalization(self):
        from datetime import date,timedelta
        from actions.models import Plan
        steps=self.plan();steps[-1]['values']['whatsapp_conversation_date']=date.today().strftime('%m/%d/%Y')
        p=self.engine().prepare(uuid.uuid4().hex,steps)
        self.assertEqual(Plan.objects.get(pk=p['id']).snapshots['__preview__']['orders'][0]['deadline'],(date.today()+timedelta(days=5)).isoformat())
        self.assertEqual(self.engine().execute(p['id'])['state'],'succeeded')

    def test_form_boundaries_and_exact_zero_compatibility(self):
        for value in ['-1','NaN','sNaN','Infinity','-Infinity']:
            steps=self.plan();steps[-1]['values']['advance_payment']=value
            self.refused(steps,'payment_not_supported')
        for field,value in [('season',''),('editor',99999999),('match_package',99),('whatsapp_conversation_date','bad')]:
            steps=self.plan();steps[-1]['values'][field]=value
            self.refused(steps,'invalid_video')
        steps=self.plan();steps[-1]['values']['whatsapp_conversation_date']='9999-12-31'
        self.refused(steps,'invalid_deadline')
        for value in ['0','0.00','-0.00','0E+2']:
            steps=self.plan();steps[-1]['values']['advance_payment']=value
            before=self.footprint();p=self.engine().prepare(uuid.uuid4().hex,steps)
            self.assertEqual(self.footprint(),before)
            self.assertEqual(self.engine().status(p['id'])['state'],'prepared')
    def test_prepare_never_calls_save_or_business_apply(self):
        from unittest.mock import patch
        from gestion_joueurs.forms import VideoForm
        from actions.engine import Engine
        # Spies only on forbidden mutation entrances, real validation/ORM reads.
        with patch.object(VideoForm,'save',side_effect=AssertionError('save during prepare')),patch.object(Engine,'_apply',side_effect=AssertionError('apply during prepare')):
            self.engine().prepare(uuid.uuid4().hex,self.plan())

    def test_invalid_player_form_refused_before_plan(self):
        steps=self.plan();steps[0]['values']['position']='ZZ'
        self.refused(steps,'invalid_player')

    def test_invalid_link_package_refused_before_plan(self):
        steps=self.plan();steps[1]['values']['expected_matches']=99
        self.refused(steps,'invalid_link')

# The base is only a fixture supplier; avoid loading its older contract tests.
for _name in list(vars(ActionsTests)):
    if _name.startswith('test_') and _name not in vars(CompatibilityTests):
        setattr(CompatibilityTests,_name,None)
del ActionsTests

class HttpCompatibilityTests(unittest.TestCase):
    def test_real_socket_refusals_and_approved_order_readback(self):
        import threading
        from datetime import date,timedelta
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from django.contrib.auth.models import User
        from django.core.wsgi import get_wsgi_application
        from django.test import override_settings
        from django.utils import timezone
        from actions.http import issue_approval
        from gestion_joueurs.models import Video,VideoEditor,Player
        from client_portal.models import Organization
        actor=User.objects.create(username='FICTION_HTTP_COMPAT_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        editor=VideoEditor.objects.create(user=actor)
        org=Organization.objects.create(name='FICTION_HTTP_COMPAT',kind='agent')
        name='FICTION_HTTP_PLAYER_'+uuid.uuid4().hex
        steps=[{'as':'p','op':'player.create','values':{'name':name,'club':'FICTION','league':'OC','position':'MF','date_of_birth':'2002-01-02'}},
               {'as':'link','op':'organization.link','values':{'player':{'ref':'p'},'organization':org.pk,'expected_matches':5}},
               {'as':'v','op':'video.order','values':{'player':{'ref':'p'},'editor':editor.pk,'client_organization':org.pk,'whatsapp_conversation_date':date.today().isoformat(),'deadline_from_whatsapp':True,'match_package':5,'season':'2025/2026','advance_payment':'0.00','info':'FICTION HTTP COMPAT'}}]
        token=uuid.uuid4().hex
        credential={'actor':actor.pk,'scopes':['catalogue','prepare','execute','status',*['op:'+s['op'] for s in steps]],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False}
        class QuietHandler(WSGIRequestHandler):
            def log_message(self,*args):pass
        options={'ACTIONS_ENABLED':True,'ACTIONS_APPROVAL_KEY':'FICTION-'+uuid.uuid4().hex,'ACTIONS_CREDENTIALS':{hashlib.sha256(token.encode()).hexdigest():credential},'MIDDLEWARE':['actions.http.OperationalWriterBoundary'],'ACTIONS_GLOBAL_LIMIT':1000,'ACTIONS_ACTOR_LIMIT':1000,'ALLOWED_HOSTS':['127.0.0.1']}
        with override_settings(**options):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=QuietHandler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def call(op,data=None):
                    request=Request('http://127.0.0.1:55573/actions/v1/'+op,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                    try:
                        with urlopen(request,timeout=5) as r:return r.status,json.load(r)
                    except HTTPError as r:return r.code,json.load(r)
                self.assertIn('video.order',call('catalogue')[1]['catalogue'])
                from copy import deepcopy
                for field,value in [('advance_payment','1'),('deadline_from_whatsapp',False),('season','INVALID')]:
                    bad=deepcopy(steps);bad[-1]['values'][field]=value
                    key=uuid.uuid4().hex;before=CompatibilityTests.footprint(self)
                    code,result=call('prepare',{'key':key,'steps':bad})
                    self.assertEqual((code,result),(400,{'error':'invalid_request'}))
                    self.assertFalse(Plan.objects.filter(actor_id=actor.pk,key=key).exists())
                    self.assertEqual(CompatibilityTests.footprint(self),before)
                code,p=call('prepare',{'key':uuid.uuid4().hex,'steps':steps});self.assertEqual(code,200)
                self.assertFalse(Player.objects.filter(name=name).exists())
                self.assertEqual(p['preview']['orders'][0]['price'],'350.00')
                self.assertEqual(call('execute',{'id':p['id'],'approval':'invalid'})[0],403)
                approval=issue_approval(p['id'],actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                code,result=call('execute',{'id':p['id'],'approval':approval});self.assertEqual(code,200)
                self.assertEqual(result['state'],'succeeded')
                self.assertEqual(call('status',{'id':p['id']})[1],result)
                self.assertEqual(call('execute',{'id':p['id'],'approval':approval})[1],result)
                video=Video.objects.get(pk=result['results']['v'])
                self.assertEqual(str(video.total_payment),'350.00');self.assertEqual(video.advance_payment,0)
                self.assertEqual(video.deadline,date.today()+timedelta(days=5))
                self.assertEqual(video.invoices.created_by_id,actor.pk)
                from pathlib import Path
                Path(__file__).with_name('http-compatibility-result.json').write_text(json.dumps({'id':p['id'],'digest':p['digest'],'results':result['results'],'state':result['state'],'effects':result['effects'],'actor':actor.pk},indent=2))
            finally:
                server.shutdown();server.server_close();thread.join(5)
                self.assertFalse(thread.is_alive())
