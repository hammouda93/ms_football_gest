import unittest,uuid,json
from django.contrib.auth.models import User
from django.db import connection
from client_portal.models import Organization
from actions.engine import Engine
from actions.models import Plan

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.actor=User.objects.create(username='FICTION_GENERAL_'+uuid.uuid4().hex,is_active=True,is_superuser=True)
        self.org=Organization.objects.create(name='FICTION_ORG',kind='agent',country='Tunisie',created_by=self.actor)
        self.engine=Engine(self.actor.pk)
    def step(self,op='organization.details.amend',**values):
        return {'as':'target','op':op,'values':{'id':self.org.pk,**values}}
    def test_http_scope_denial_precedes_object_reads(self):
        import hashlib
        from datetime import timedelta
        from django.test import Client,override_settings
        from django.test.utils import CaptureQueriesContext
        from django.utils import timezone
        token=uuid.uuid4().hex
        credential={'actor':self.actor.pk,'scopes':['prepare'],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False}
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():credential},MIDDLEWARE=['actions.http.WriterBoundary']):
            with CaptureQueriesContext(connection) as queries:
                response=Client(HTTP_AUTHORIZATION='Bearer '+token).post('/actions/v1/prepare',data=json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'p','op':'prospect.details.amend','values':{'id':99999999,'country':'France'}}]}),content_type='application/json')
            self.assertEqual(response.status_code,403,response.content)
            self.assertFalse(any('prospects_prospect' in q['sql'] for q in queries))

    def test_socket_roundtrip_both_adapters_and_readback(self):
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from django.test import override_settings
        from django.utils import timezone
        from datetime import timedelta
        from urllib.request import Request,urlopen
        from actions.http import issue_approval
        from prospects.models import Prospect
        import threading,hashlib
        prospect=Prospect.objects.create(full_name='FICTION_SOCKET',whatsapp_number='+21620123456',position='midfielder',league='OC',season='2025/2026',service_type='highlights',match_links='https://example.org/match')
        token=uuid.uuid4().hex
        credential={'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status','op:organization.details.amend','op:prospect.details.amend'],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False}
        overrides={'ACTIONS_ENABLED':True,'ACTIONS_APPROVAL_KEY':'FICTION-'+uuid.uuid4().hex,'ACTIONS_CREDENTIALS':{hashlib.sha256(token.encode()).hexdigest():credential},'MIDDLEWARE':['actions.http.OperationalWriterBoundary'],'ACTIONS_GLOBAL_LIMIT':1000,'ACTIONS_ACTOR_LIMIT':1000,'ALLOWED_HOSTS':['127.0.0.1']}
        class QuietHandler(WSGIRequestHandler):
            def log_message(self,*args):pass
        with override_settings(**overrides):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=QuietHandler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def call(operation,data=None):
                    raw=json.dumps(data).encode() if data is not None else None
                    request=Request('http://127.0.0.1:55573/actions/v1/'+operation,data=raw,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                    with urlopen(request,timeout=5) as response:return json.load(response)
                catalogue=call('catalogue')['catalogue'];self.assertEqual(len(catalogue),2)
                steps=[self.step(name='FICTION_SOCKET_NEW'),{'as':'p','op':'prospect.details.amend','values':{'id':prospect.pk,'internal_notes':'SOCKET_NOTE'}}]
                p=call('prepare',{'key':uuid.uuid4().hex,'steps':steps})
                self.assertEqual(len(p['preview']['changes']),2)
                approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                result=call('execute',{'id':p['id'],'approval':approval})
                self.assertEqual(result['state'],'succeeded');self.assertEqual(call('status',{'id':p['id']}),result)
                self.assertEqual(Organization.objects.get(pk=self.org.pk).name,'FICTION_SOCKET_NEW')
                self.assertEqual(Prospect.objects.get(pk=prospect.pk).internal_notes,'SOCKET_NOTE')
                from pathlib import Path
                Path(__file__).with_name('socket-result.json').write_text(json.dumps({'plan':p['id'],'digest':p['digest'],'organization':self.org.pk,'prospect':prospect.pk,'state':result['state'],'effects':result['effects'],'readback':True},indent=2))
            finally:
                server.shutdown();server.server_close();thread.join(5)
                self.assertFalse(thread.is_alive())

    def test_composed_new_family_exact_business_footprint_and_idempotency(self):
        from django.apps import apps
        from django.core import mail
        from prospects.models import Prospect
        prospect=Prospect.objects.create(full_name='FICTION_FOOTPRINT',whatsapp_number='+21620123456',position='midfielder',league='OC',season='2025/2026',service_type='highlights',match_links='https://example.org/match')
        models=[m for m in apps.get_models() if m._meta.app_label in {'gestion_joueurs','client_portal','prospects','sportsbase_data'}]
        def footprint():return {m._meta.label:json.dumps(list(m.objects.order_by('pk').values()),sort_keys=True,default=str) for m in models if m not in (Organization,Prospect)}
        before=footprint();outbox=len(getattr(mail,'outbox',[]))
        steps=[self.step(contact_name='FICTION_CONTACT'),{'as':'prospect','op':'prospect.details.amend','values':{'id':prospect.pk,'club':'FICTION_CLUB'}}]
        key=uuid.uuid4().hex;p=self.engine.prepare(key,steps)
        self.assertEqual(footprint(),before)
        r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded')
        self.assertEqual(r['effects'],{'history':[],'notifications':[],'invoices':[]})
        self.assertEqual(footprint(),before);self.assertEqual(len(getattr(mail,'outbox',[])),outbox)
        self.assertEqual(self.engine.prepare(key,steps)['id'],p['id'])
        self.assertEqual(self.engine.execute(p['id']),r)
        altered=[self.step(contact_name='DIFFERENT')]
        with self.assertRaisesRegex(ValueError,'idempotency_mismatch'):self.engine.prepare(key,altered)
        self.assertEqual(Organization.objects.get(pk=self.org.pk).contact_name,'FICTION_CONTACT')
        self.assertEqual(Prospect.objects.get(pk=prospect.pk).club,'FICTION_CLUB')

    def test_strict_fields_types_real_form_errors_no_orphan(self):
        cases=[({'email':'x@example.org'},'field_forbidden'),({'is_active':False},'field_forbidden'),({'name':True},'invalid_type'),({'name':'x'*161},'invalid_form'),({},'empty_amendment')]
        for values,code in cases:
            key=uuid.uuid4().hex
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError,code):self.engine.prepare(key,[self.step(**values)])
                self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=key).exists())
        self.assertEqual(Organization.objects.get(pk=self.org.pk).name,'FICTION_ORG')

    def test_permissions_and_snapshots_rechecked(self):
        steps=[self.step(name='FICTION_PENDING')]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        Organization.objects.filter(pk=self.org.pk).update(contact_name='HUMAN_EDIT')
        r=self.engine.execute(p['id']);self.assertEqual((r['state'],r['error']),('failed','conflict'))
        self.assertEqual(Organization.objects.get(pk=self.org.pk).name,'FICTION_ORG')
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        Organization.objects.filter(pk=self.org.pk).update(is_active=False)
        with self.assertRaisesRegex(PermissionError,'object_permission_denied'):self.engine.execute(p['id'])
        with self.assertRaisesRegex(PermissionError,'object_permission_denied'):self.engine.prepare(uuid.uuid4().hex,steps)
        User.objects.filter(pk=self.actor.pk).update(is_superuser=False)
        with self.assertRaisesRegex(PermissionError,'permission_denied'):self.engine.status(p['id'])

    def test_approval_digest_covers_old_new_exclusions_and_contract(self):
        from copy import deepcopy
        steps=[self.step(country='France')]
        p=self.engine.prepare(uuid.uuid4().hex,steps);saved=Plan.objects.get(pk=p['id'])
        for field in ['old','new','excluded','contract']:
            snapshot=deepcopy(saved.snapshots)
            snapshot['__preview__']['changes'][0][field]='TAMPERED'
            self.assertNotEqual(Engine.proposal_digest(steps,snapshot),saved.digest)
        Plan.objects.filter(pk=p['id']).update(snapshots=snapshot)
        with self.assertRaisesRegex(ValueError,'plan_integrity'):self.engine.execute(p['id'])
        self.assertEqual(Organization.objects.get(pk=self.org.pk).country,'Tunisie')

    def test_duplicate_target_in_simple_family_is_refused_before_plan_creation(self):
        key=uuid.uuid4().hex
        with self.assertRaisesRegex(ValueError,'duplicate_target'):
            self.engine.prepare(key,[self.step(name='FIRST'),{'as':'second','op':'organization.details.amend','values':{'id':self.org.pk,'name':'SECOND'}}])
        self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=key).exists())

    def test_http_catalogue_scopes_and_approved_durable_execution(self):
        import hashlib
        from datetime import timedelta
        from django.test import Client,override_settings
        from django.utils import timezone
        from actions.http import issue_approval
        token=uuid.uuid4().hex
        credential={'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status','op:organization.details.amend'],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False}
        settings={'ACTIONS_ENABLED':True,'ACTIONS_APPROVAL_KEY':'FICTION-'+uuid.uuid4().hex,'ACTIONS_CREDENTIALS':{hashlib.sha256(token.encode()).hexdigest():credential},'MIDDLEWARE':['actions.http.OperationalWriterBoundary'],'ACTIONS_GLOBAL_LIMIT':1000,'ACTIONS_ACTOR_LIMIT':1000}
        client=Client(HTTP_AUTHORIZATION='Bearer '+token)
        def post(op,value):return client.post('/actions/v1/'+op,data=json.dumps(value),content_type='application/json')
        with override_settings(**settings):
            cat=client.get('/actions/v1/catalogue').json()['catalogue']
            self.assertEqual(set(cat),{'organization.details.amend'})
            denied=post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'p','op':'prospect.details.amend','values':{'id':1,'country':'X'}}]})
            self.assertEqual(denied.status_code,403)
            response=post('prepare',{'key':uuid.uuid4().hex,'steps':[self.step(name='FICTION_HTTP')]})
            self.assertEqual(response.status_code,200,response.content)
            p=response.json()
            self.assertEqual(post('execute',{'id':p['id'],'approval':'invalid'}).status_code,403)
            self.assertEqual(Organization.objects.get(pk=self.org.pk).name,'FICTION_ORG')
            approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
            result=post('execute',{'id':p['id'],'approval':approval})
            self.assertEqual(result.status_code,200,result.content)
            self.assertEqual(result.json()['state'],'succeeded')
            self.assertEqual(post('status',{'id':p['id']}).json(),result.json())
            self.assertEqual(post('execute',{'id':p['id'],'approval':approval}).json(),result.json())
            import psycopg2
            c=psycopg2.connect(host='127.0.0.1',port=55572,user='msf_unified_fixed_fixture',dbname='msf_unified_fixed_fiction')
            try:
                with c.cursor() as q:
                    q.execute('SELECT name FROM client_portal_organization WHERE id=%s',(self.org.pk,))
                    self.assertEqual(q.fetchone()[0],'FICTION_HTTP')
            finally:c.close()

    def test_prospect_notes_uses_management_form_and_preserves_conversion(self):
        from prospects.models import Prospect
        prospect=Prospect.objects.create(full_name='FICTION_PROSPECT',whatsapp_number='+21620123456',position='midfielder',league='OC',season='2025/2026',service_type='highlights',match_links='https://example.org/match',internal_notes='before')
        before=Prospect.objects.values().get(pk=prospect.pk)
        steps=[{'as':'p','op':'prospect.details.amend','values':{'id':prospect.pk,'internal_notes':' after ','country':' France '}}]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        self.assertEqual(Prospect.objects.values().get(pk=prospect.pk),before)
        r=self.engine.execute(p['id']);self.assertEqual(r['state'],'succeeded')
        after=Prospect.objects.values().get(pk=prospect.pk)
        self.assertEqual(after['internal_notes'],'after');self.assertEqual(after['country'],'France')
        for k in before.keys()-{'internal_notes','country'}:self.assertEqual(before[k],after[k],k)
        self.assertEqual(self.engine.status(p['id']),r)
        self.assertEqual(self.engine.catalogue()['prospect.details.amend']['schema']['country']['maxLength'],80)

    def test_organization_form_amendment_prepare_execute_status_readback(self):
        before=Organization.objects.values().get(pk=self.org.pk)
        steps=[self.step(name='FICTION_NEW',country=' France ')]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        self.assertEqual(Organization.objects.values().get(pk=self.org.pk),before)
        saved=Plan.objects.get(pk=p['id'])
        change=saved.snapshots['__preview__']['changes'][0]
        self.assertEqual(change['old'],{'name':'FICTION_ORG','country':'Tunisie'})
        self.assertEqual(change['new'],{'name':'FICTION_NEW','country':'France'})
        self.assertIn('is_active',change['excluded'])
        result=self.engine.execute(p['id'])
        self.assertEqual(result['state'],'succeeded')
        after=Organization.objects.values().get(pk=self.org.pk)
        self.assertEqual(after['name'],'FICTION_NEW');self.assertEqual(after['country'],'France')
        for k in before.keys()-{'name','country'}:self.assertEqual(before[k],after[k],k)
        self.assertEqual(self.engine.status(p['id']),result)
        self.assertEqual(self.engine.execute(p['id']),result)
        catalogue=self.engine.catalogue()['organization.details.amend']
        self.assertEqual(catalogue['schema']['name']['maxLength'],160)
        self.assertEqual(catalogue['fields'],['id','name','contact_name','country'])
