"""Real PostgreSQL, forms, middleware and HTTP; fixture records only."""
import unittest,uuid,json,hashlib,threading
from datetime import date,timedelta
from pathlib import Path
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from django.test import override_settings
from actions.engine import Engine
from actions.models import Plan
from actions.http import issue_approval
from gestion_joueurs.models import Player
from client_portal.models import Organization
from prospects.models import Prospect
ROOT=Path(__file__).resolve().parent

class DeclarativeTests(unittest.TestCase):
    def setUp(self):
        self.actor=User.objects.create(username='FICTION_DECL_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        self.engine=Engine(self.actor.pk)
        self.player=Player.objects.create(name='FICTION_DECL',club='OLD',league='OC',position='MF',date_of_birth=date(2001,1,2))
    def step(self,op,values,alias='record'):
        return {'as':alias,'op':op,'values':values}
    def test_calculated_age_is_not_declared_excluded(self):
        contract=self.engine.catalogue()['player.profile.amend']
        self.assertNotIn('age',contract['excludedFields'])
        self.assertEqual(contract['calculatedFields'],['age'])

    def test_concurrent_http_same_creation_plan_has_one_committed_row(self):
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer,WSGIRequestHandler,make_server
        from django.core.wsgi import get_wsgi_application
        from urllib.request import Request,urlopen
        name='FICTION_CONCURRENT_'+uuid.uuid4().hex
        steps=[self.step('organization.profile.create',{'name':name,'kind':'club'})]
        plan=self.engine.prepare(uuid.uuid4().hex,steps);p=Plan.objects.get(pk=plan['id'])
        token=uuid.uuid4().hex;cred={'actor':self.actor.pk,'scopes':['execute','op:organization.profile.create'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        class Server(ThreadingMixIn,WSGIServer):daemon_threads=True
        class Quiet(WSGIRequestHandler):
            def log_message(self,*a):pass
        opts=dict(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1'],ACTIONS_GLOBAL_LIMIT=10000,ACTIONS_ACTOR_LIMIT=10000,ACTIONS_LOCK_TIMEOUT_MS=2000)
        results=[];errors=[];barrier=threading.Barrier(3)
        with override_settings(**opts):
            approval=issue_approval(p.pk,self.actor.pk,p.digest,timezone.now()+timedelta(minutes=2))
            server=make_server('127.0.0.1',55573,get_wsgi_application(),server_class=Server,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def worker():
                try:
                    barrier.wait(5)
                    req=Request('http://127.0.0.1:55573/actions/v1/execute',data=json.dumps({'id':plan['id'],'approval':approval}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                    with urlopen(req,timeout=10) as r:results.append(json.load(r))
                except Exception as e:errors.append(type(e).__name__)
            workers=[threading.Thread(target=worker) for _ in range(2)]
            try:
                for w in workers:w.start()
                barrier.wait(5)
                for w in workers:w.join(15);self.assertFalse(w.is_alive())
                self.assertEqual(errors,[]);self.assertEqual(len(results),2)
                self.assertEqual(results[0],results[1]);self.assertEqual(results[0]['state'],'succeeded')
                self.assertEqual(Organization.objects.filter(name=name).count(),1)
                ROOT.joinpath('concurrent-mission.json').write_text(json.dumps({'plan':plan['id'],'results':results,'count':1},indent=2))
            finally:
                server.shutdown();server.server_close();thread.join(5)

    def test_profile_alias_membership_changes_conflict_before_order(self):
        from gestion_joueurs.models import VideoEditor,Video
        from client_portal.models import OrganizationPlayer
        editor_user=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex)
        editor=VideoEditor.objects.create(user=editor_user)
        org=Organization.objects.create(name='FICTION_ALIAS',kind='academy')
        link=OrganizationPlayer.objects.create(player=self.player,organization=org,expected_matches=3,is_active=True)
        steps=[self.step('player.profile.amend',{'id':self.player.pk,'club':'ALIAS_NEW'},'p'),self.step('video.order',{'player':{'ref':'p'},'editor':editor.pk,'client_organization':org.pk,'whatsapp_conversation_date':date.today().isoformat(),'deadline_from_whatsapp':True,'match_package':3,'season':'2025/2026','advance_payment':'0','info':'FICTION_ALIAS'},'v')]
        prepared=self.engine.prepare(uuid.uuid4().hex,steps)
        # Human changes and restores relevant visible fields but membership metadata drifts.
        OrganizationPlayer.objects.filter(pk=link.pk).update(expected_matches=5)
        result=self.engine.execute(prepared['id'])
        self.assertEqual((result['state'],result['error']),('failed','conflict'))
        self.assertFalse(Video.objects.filter(player=self.player).exists())
        self.assertEqual(Player.objects.get(pk=self.player.pk).club,'OLD')

    def test_player_profile_creation_shared_family_and_duplicate_guard(self):
        values={'name':'FICTION_CREATE_'+uuid.uuid4().hex,'club':' Club ','league':'OC','position':'MF','date_of_birth':'2004-05-06','whatsapp_number':'+21620123456'}
        before=Player.objects.count();steps=[self.step('player.profile.create',values)]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        self.assertEqual(Player.objects.count(),before)
        change=Plan.objects.get(pk=p['id']).snapshots['__preview__']['changes'][0]
        self.assertEqual(change['old'],None);self.assertIn('age',change['new'])
        result=self.engine.execute(p['id']);self.assertEqual(result['state'],'succeeded',result)
        player=Player.objects.get(pk=result['results']['record'])
        self.assertEqual(player.club,'Club');self.assertEqual(player.age,change['new']['age'])
        duplicate=self.engine.prepare(uuid.uuid4().hex,steps)
        refused=self.engine.execute(duplicate['id']);self.assertEqual((refused['state'],refused['error']),('failed','duplicate_record'))
        self.assertEqual(Player.objects.count(),before+1)
        ROOT.joinpath('player-create-mission.json').write_text(json.dumps({'plan':p,'result':result,'duplicate':refused,'preview':change,'row':Player.objects.values().get(pk=player.pk)},default=str,indent=2))

    def test_new_contracts_denials_conflicts_permissions_and_integrity(self):
        from copy import deepcopy
        from django.test import Client
        from django.test.utils import CaptureQueriesContext
        org=Organization.objects.create(name='FICTION_NEGATIVE',kind='agent')
        prospect=Prospect.objects.create(full_name='FICTION_NEGATIVE',whatsapp_number='+21620123456',league='OC',position='midfielder',season='2026/2027',service_type='highlights',match_links='https://example.org/match')
        fixtures=[('player.profile.amend',self.player,'name'),('organization.profile.amend',org,'name'),('prospect.profile.amend',prospect,'full_name')]
        records=[]
        for op,obj,field in fixtures:
            old=obj.__class__.objects.values().get(pk=obj.pk)
            for values in [{'id':obj.pk,'email':'x@example.org'},{'id':obj.pk,'status':'converted'},{'id':obj.pk,field:True},{'id':obj.pk,'model':'auth.User'},{'id':obj.pk}]:
                key=uuid.uuid4().hex
                with self.assertRaises(ValueError):self.engine.prepare(key,[self.step(op,values)])
                self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=key).exists())
            p=self.engine.prepare(uuid.uuid4().hex,[self.step(op,{'id':obj.pk,field:'FICTION_REQUESTED'})])
            obj.__class__.objects.filter(pk=obj.pk).update(**{field:'FICTION_HUMAN_EDIT'})
            result=self.engine.execute(p['id']);self.assertEqual((result['state'],result['error']),('failed','conflict'))
            self.assertEqual(obj.__class__.objects.values().get(pk=obj.pk),dict(old,**{field:'FICTION_HUMAN_EDIT'}))
            records.append({'operation':op,'conflict':result})
            token=uuid.uuid4().hex
            cred={'actor':self.actor.pk,'scopes':['prepare','execute'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
            opts=dict(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ACTIONS_GLOBAL_LIMIT=10000,ACTIONS_ACTOR_LIMIT=10000)
            steps=[self.step(op,{'id':obj.pk,field:'FICTION_SCOPE'})]
            prepared=self.engine.prepare(uuid.uuid4().hex,steps);plan=Plan.objects.get(pk=prepared['id'])
            with override_settings(**opts):
                client=Client(HTTP_AUTHORIZATION='Bearer '+token)
                approval=issue_approval(plan.pk,self.actor.pk,plan.digest,timezone.now()+timedelta(minutes=2))
                for route,payload in [('prepare',{'key':uuid.uuid4().hex,'steps':steps}),('execute',{'id':prepared['id'],'approval':approval})]:
                    with CaptureQueriesContext(connection) as queries:
                        response=client.post('/actions/v1/'+route,data=json.dumps(payload),content_type='application/json')
                    self.assertEqual(response.status_code,403,response.content)
                    self.assertFalse(any(obj._meta.db_table in q['sql'] for q in queries))
            snap=deepcopy(plan.snapshots);snap['__preview__']['changes'][0]['new'][field]='TAMPERED'
            Plan.objects.filter(pk=plan.pk).update(snapshots=snap)
            with self.assertRaisesRegex(ValueError,'plan_integrity'):self.engine.execute(plan.pk)
        for op,values in [('player.profile.amend',{'id':self.player.pk,'date_of_birth':'not-date'}),('prospect.profile.amend',{'id':prospect.pk,'position':'FW'}),('organization.profile.create',{'name':'FICTION_BAD','kind':'not-kind'})]:
            with self.assertRaisesRegex(ValueError,'invalid_form'):self.engine.prepare(uuid.uuid4().hex,[self.step(op,values)])
        steps=[self.step('organization.profile.create',{'name':'FICTION_PERMISSIONS','kind':'club'})]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        with self.assertRaisesRegex(ValueError,'idempotency_mismatch'):
            self.engine.prepare(Plan.objects.get(pk=p['id']).key,[self.step('organization.profile.create',{'name':'DIFFERENT','kind':'club'})])
        User.objects.filter(pk=self.actor.pk).update(is_superuser=False)
        for action in [lambda:self.engine.prepare(uuid.uuid4().hex,steps),lambda:self.engine.execute(p['id'])]:
            with self.assertRaisesRegex(PermissionError,'permission_denied'):action()
        ROOT.joinpath('negative-cases.json').write_text(json.dumps(records,indent=2))

    def test_profiles_new_combinations_exact_footprint_and_excluded_contract(self):
        from django.apps import apps
        from django.core import mail
        org=Organization.objects.create(name='FICTION_COMBINATIONS',kind='club',country='Tunisie')
        prospect=Prospect.objects.create(full_name='FICTION_COMBINATIONS',whatsapp_number='+21620123456',league='OC',position='midfielder',season='2026/2027',service_type='highlights',match_links='https://example.org/match')
        models=[m for m in apps.get_models() if m._meta.app_label in {'gestion_joueurs','client_portal','prospects','sportsbase_data'}]
        def footprint():return {m._meta.label:list(m.objects.order_by('pk').values()) for m in models}
        combos=[
            [('organization.profile.amend',{'id':org.pk,'whatsapp_number':'+21620999888','contact_name':' Responsable '}),('player.profile.amend',{'id':self.player.pk,'name':'NOM_REVU','position':'DF'})],
            [('prospect.profile.amend',{'id':prospect.pk,'club':' Nouveau club ','message':' Précision libre '})],
            [('organization.profile.amend',{'id':org.pk,'country':' Algérie ','name':'FICTION_RENAMED'}),('player.profile.amend',{'id':self.player.pk,'whatsapp_number':'','club':'CLUB_2'})],
        ]
        missions=[]
        for combo in combos:
            steps=[self.step(op,values,'s'+str(i)) for i,(op,values) in enumerate(combo)]
            before=footprint();mail_before=len(getattr(mail,'outbox',[]));p=self.engine.prepare(uuid.uuid4().hex,steps)
            self.assertEqual(footprint(),before)
            saved=Plan.objects.get(pk=p['id']);changes=saved.snapshots['__preview__']['changes']
            for change in changes:
                self.assertIn('email',change['contract']['excludedFields'])
            result=self.engine.execute(p['id']);self.assertEqual(result['state'],'succeeded',result)
            after=footprint()
            expected=json.loads(json.dumps(before,default=str))
            for change in changes:
                label=change['contract']['model'];row=next(r for r in expected[label] if r['id']==change['id']);row.update(change['new'])
            self.assertEqual(json.loads(json.dumps(after,default=str)),expected)
            self.assertEqual(result['effects'],{'history':[],'notifications':[],'invoices':[]})
            self.assertEqual(len(getattr(mail,'outbox',[])),mail_before)
            missions.append({'id':p['id'],'steps':steps,'changes':changes,'result':result,'all_business_tables_exact':True})
        ROOT.joinpath('combination-missions.json').write_text(json.dumps(missions,indent=2))

    def test_bounded_lookup_requires_scope_before_target_queries(self):
        from django.test import Client
        from django.test.utils import CaptureQueriesContext
        token=uuid.uuid4().hex
        cred={'actor':self.actor.pk,'scopes':['lookup'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        options=dict(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ACTIONS_GLOBAL_LIMIT=10000,ACTIONS_ACTOR_LIMIT=10000)
        client=Client(HTTP_AUTHORIZATION='Bearer '+token)
        payload={'operation':'player.profile.amend','prefix':'FICTION','limit':2}
        with override_settings(**options):
            with CaptureQueriesContext(connection) as queries:
                response=client.post('/actions/v1/lookup',data=json.dumps(payload),content_type='application/json')
            self.assertEqual(response.status_code,403,response.content)
            self.assertFalse(any('gestion_joueurs_player' in q['sql'] for q in queries))
            cred['scopes'].append('op:player.profile.amend')
            response=client.post('/actions/v1/lookup',data=json.dumps(payload),content_type='application/json')
            self.assertEqual(response.status_code,200,response.content)
            result=response.json();self.assertLessEqual(len(result['rows']),2)
            self.assertTrue(all(set(r)=={'id','label'} for r in result['rows']))
            for bad in [dict(payload,limit=21),dict(payload,limit=True),dict(payload,prefix='F'),dict(payload,model='auth.User')]:
                self.assertEqual(client.post('/actions/v1/lookup',data=json.dumps(bad),content_type='application/json').status_code,400)
            ROOT.joinpath('lookup-result.json').write_text(json.dumps(result,indent=2))

    def test_organization_creation_and_profiles_composed_socket(self):
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        from django.core.wsgi import get_wsgi_application
        from urllib.request import Request,urlopen
        prospect=Prospect.objects.create(full_name='FICTION_PROSPECT',whatsapp_number='+21620123456',league='OC',position='midfielder',season='2026/2027',service_type='highlights',match_links='https://example.org/match')
        token=uuid.uuid4().hex
        ops=['organization.profile.create','organization.profile.amend','player.profile.amend','prospect.profile.amend']
        credential={'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status',*['op:'+o for o in ops]],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        overrides=dict(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():credential},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1'],ACTIONS_GLOBAL_LIMIT=10000,ACTIONS_ACTOR_LIMIT=10000)
        class Quiet(WSGIRequestHandler):
            def log_message(self,*a):pass
        with override_settings(**overrides):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                def call(route,payload=None):
                    req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=None if payload is None else json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                    with urlopen(req,timeout=10) as r:return json.load(r)
                cat=call('catalogue')['catalogue'];self.assertEqual(set(cat),set(ops))
                steps=[self.step('organization.profile.create',{'name':' FICTION_ACADEMY_'+uuid.uuid4().hex,'kind':'academy','country':' Tunisie ','contact_name':' Contact ','whatsapp_number':'+21620123456'},'org'),self.step('player.profile.amend',{'id':self.player.pk,'club':'CLUB_NEW','league':'LY'},'player'),self.step('prospect.profile.amend',{'id':prospect.pk,'full_name':' FICTION_PROFILE ','date_of_birth':'2005-03-04','country':' France ','league':'L2','position':'forward','whatsapp_number':'+216 20 123 456','message':' Nouvelle précision ','internal_notes':' Note interne '},'prospect')]
                old_player=Player.objects.values().get(pk=self.player.pk);old_prospect=Prospect.objects.values().get(pk=prospect.pk);count=Organization.objects.count()
                key=uuid.uuid4().hex;p=call('prepare',{'key':key,'steps':steps})
                self.assertEqual(Organization.objects.count(),count)
                self.assertEqual(Player.objects.values().get(pk=self.player.pk),old_player)
                self.assertEqual(Prospect.objects.values().get(pk=prospect.pk),old_prospect)
                self.assertEqual(p['preview']['changes'][0]['new']['created_by_id'],self.actor.pk)
                self.assertEqual(p['preview']['changes'][0]['new']['is_active'],True)
                approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                result=call('execute',{'id':p['id'],'approval':approval});self.assertEqual(result['state'],'succeeded',result)
                self.assertEqual(call('status',{'id':p['id']}),result)
                self.assertEqual(call('execute',{'id':p['id'],'approval':approval}),result)
                self.assertEqual(call('prepare',{'key':key,'steps':steps})['id'],p['id'])
                org=Organization.objects.get(pk=result['results']['org']);self.assertEqual((org.kind,org.country,org.created_by_id),('academy','Tunisie',self.actor.pk))
                self.assertEqual(Organization.objects.count(),count+1)
                row=Prospect.objects.values().get(pk=prospect.pk)
                for field in set(old_prospect)-set(steps[2]['values']):self.assertEqual(row[field],old_prospect[field],field)
                self.assertEqual(row['whatsapp_number'],'+21620123456')
                ROOT.joinpath('composed-mission.json').write_text(json.dumps({'plan':p,'result':result,'expected':{'organization':dict(Organization.objects.values().get(pk=org.pk)),'player':dict(Player.objects.values().get(pk=self.player.pk)),'prospect':row}},default=str,indent=2))
            finally:
                server.shutdown();server.server_close();thread.join(5);self.assertFalse(thread.is_alive())

    def test_player_profile_dynamic_form_preview_and_calculated_age(self):
        before=Player.objects.values().get(pk=self.player.pk)
        steps=[self.step('player.profile.amend',{'id':self.player.pk,'name':' FICTION_NEW ','date_of_birth':'2003-07-15','league':'L2','position':'FW','whatsapp_number':'+21620123456'})]
        p=self.engine.prepare(uuid.uuid4().hex,steps)
        self.assertEqual(Player.objects.values().get(pk=self.player.pk),before)
        saved=Plan.objects.get(pk=p['id']);change=saved.snapshots['__preview__']['changes'][0]
        today=date.today();age=today.year-2003-((today.month,today.day)<(7,15))
        self.assertEqual(change['new'],{'name':'FICTION_NEW','date_of_birth':'2003-07-15','league':'L2','position':'FW','whatsapp_number':'+21620123456','age':age})
        self.assertEqual(change['old']['date_of_birth'],'2001-01-02')
        self.assertIn('email',change['excluded']);self.assertNotIn('age',change['excluded'])
        self.assertEqual(change['contract']['schema']['date_of_birth']['format'],'date')
        result=self.engine.execute(p['id']);self.assertEqual(result['state'],'succeeded',result)
        after=Player.objects.values().get(pk=self.player.pk)
        expected=dict(before,name='FICTION_NEW',date_of_birth=date(2003,7,15),league='L2',position='FW',whatsapp_number='+21620123456',age=age)
        self.assertEqual(after,expected)
        self.assertEqual(self.engine.execute(p['id']),result)
