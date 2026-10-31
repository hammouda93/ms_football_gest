"""DF-01 real HTTP/PostgreSQL regression; fixture-only approval authority."""
import contextlib,hashlib,json,threading,unittest,uuid
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from wsgiref.simple_server import make_server,WSGIRequestHandler
from django.apps import apps
from django.contrib.auth.models import User
from django.core import mail
from django.core.validators import MinValueValidator
from django.db.models.signals import pre_save,post_save,post_delete
from django.test import override_settings
from django.utils import timezone
from actions.engine import Engine
from actions.models import Plan
from actions.http import issue_approval
from gestion_joueurs.models import Player
R=Path(__file__).resolve().parent

class DF01Tests(unittest.TestCase):
    def setUp(self):
        self.actor=User.objects.create(username='FICTION_DF01_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        self.engine=Engine(self.actor.pk)
        self.player=Player.objects.create(name='FICTION_DF01',club='OLD',league='OC',position='MF',date_of_birth=date(2001,1,2))
        self.models=[m for m in apps.get_models() if m._meta.app_label in {'gestion_joueurs','client_portal','prospects','sportsbase_data'}]
        self.signals=[]
        def observe(sender,instance,**kw):
            if sender in self.models or sender is Plan:self.signals.append((sender._meta.label,instance.pk))
        self.observe=observe
        for s in [pre_save,post_save,post_delete]:s.connect(observe,weak=False)
        self.addCleanup(self.disconnect)
    def disconnect(self):
        for s in [pre_save,post_save,post_delete]:s.disconnect(self.observe)
    def footprint(self):return {m._meta.label:list(m.objects.order_by('pk').values()) for m in self.models}
    def step(self,mode,birth):
        values={'date_of_birth':birth}
        if mode=='create':values.update(name='FICTION_DF01_'+uuid.uuid4().hex,club='OLD',league='OC',position='MF')
        else:values['id']=self.player.pk
        return {'as':'p','op':'player.profile.'+mode,'values':values}
    @contextlib.contextmanager
    def http(self):
        from django.core.wsgi import get_wsgi_application
        token=uuid.uuid4().hex
        cred={'actor':self.actor.pk,'scopes':['prepare','execute','status','op:player.profile.create','op:player.profile.amend'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
        class Quiet(WSGIRequestHandler):
            def log_message(self,*args):pass
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1'],ACTIONS_QUOTA_GLOBAL=10000,ACTIONS_QUOTA_IDENTITY=10000):
            server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def call(route,payload):
                req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                try:
                    with urlopen(req,timeout=10) as response:return response.status,json.load(response)
                except HTTPError as response:return response.code,json.load(response)
            try:yield call
            finally:server.shutdown();server.server_close();thread.join(5);self.assertFalse(thread.is_alive())
    def reject_future(self,mode):
        records=[]
        with self.http() as call:
            for birth in ['2099-01-01',(date.today()+timedelta(days=1)).isoformat()]:
                with self.subTest(mode=mode,birth=birth):
                    before=self.footprint();plans=list(Plan.objects.order_by('pk').values());self.signals.clear();outbox=len(getattr(mail,'outbox',[]))
                    key=uuid.uuid4().hex;step=self.step(mode,birth)
                    status,body=call('prepare',{'key':key,'steps':[step]})
                    self.assertEqual(status,400,(mode,birth,body))
                    self.assertEqual(body,{'error':'invalid_request'})
                    self.assertEqual(self.footprint(),before)
                    self.assertEqual(list(Plan.objects.order_by('pk').values()),plans)
                    self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=key).exists())
                    self.assertEqual(self.signals,[])
                    self.assertEqual(len(getattr(mail,'outbox',[])),outbox)
                    records.append({'mode':mode,'birth':birth,'key':key,'actor':self.actor.pk,'business_unchanged':True,'plans_unchanged':True,'save_delete_signals':[],'http_status':status,'body':body})
        (R/('df01-refused-'+mode+'.json')).write_text(json.dumps(records,indent=2))
    def test_future_create_http_refused_without_plan_or_business_write(self):self.reject_future('create')
    def test_future_amend_http_refused_without_plan_or_business_write(self):self.reject_future('amend')

    def test_calculated_age_is_assigned_before_real_field_validator(self):
        from actions.declarative import DEFINITIONS
        field=Player._meta.get_field('age');real=field.clean;observed=[]
        def clean(value,instance):
            observed.append((value,instance.age,instance.date_of_birth))
            return real(value,instance)
        with patch.object(field,'clean',side_effect=clean):
            for mode in ['create','amend']:
                step=self.step(mode,'2099-01-01')
                with self.assertRaisesRegex(ValueError,'invalid_model'):DEFINITIONS[step['op']].cleaned(step['values'],self.actor.pk)
        self.assertEqual(len(observed),2)
        for value,age,birth in observed:
            self.assertLess(value,0);self.assertEqual(value,age);self.assertEqual(birth,date(2099,1,1))

    def test_age_zero_legitimate_dates_exact_preview_and_all_exclusions(self):
        records=[]
        with self.http() as call:
            for mode in ['create','amend']:
                for birth in [date.today(),date.today()-timedelta(days=1),date(2004,2,29),date(2003,7,15),None]:
                    with self.subTest(mode=mode,birth=birth):
                        step=self.step(mode,birth.isoformat() if birth else '')
                        before=self.footprint();old=Player.objects.values().get(pk=self.player.pk) if mode=='amend' else None
                        expected_age=(date.today().year-birth.year-((date.today().month,date.today().day)<(birth.month,birth.day))) if birth else (old['age'] if old else None)
                        self.signals.clear()
                        status,p=call('prepare',{'key':uuid.uuid4().hex,'steps':[step]});self.assertEqual(status,200,p)
                        self.assertEqual(self.footprint(),before)
                        self.assertFalse(any(label!='actions.Plan' for label,pk in self.signals))
                        change=p['preview']['changes'][0]
                        self.assertEqual(change['old'],None if old is None else json.loads(json.dumps({k:old[k] for k in change['new']},default=str)))
                        expected_selected={k:v for k,v in step['values'].items() if k!='id'}
                        expected_selected['date_of_birth']=birth.isoformat() if birth else None
                        if birth:expected_selected['age']=expected_age
                        if old:
                            self.assertEqual(change['new'],expected_selected)
                            self.assertEqual(set(change['excluded']),set(old)-set(expected_selected))
                        else:
                            for k,v in expected_selected.items():self.assertEqual(change['new'][k],v,k)
                            self.assertEqual(change['excluded'],[])
                        approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                        status,result=call('execute',{'id':p['id'],'approval':approval});self.assertEqual(status,200,result);self.assertEqual(result['state'],'succeeded',result)
                        self.assertEqual(call('status',{'id':p['id']}),(200,result))
                        row=Player.objects.values().get(pk=result['results']['p'])
                        self.assertEqual(row['date_of_birth'],birth);self.assertEqual(row['age'],expected_age)
                        expected=json.loads(json.dumps(before,default=str))
                        if old:
                            target=next(x for x in expected['gestion_joueurs.Player'] if x['id']==row['id']);target.update(change['new'])
                        else:
                            self.assertEqual(set(change['new'])|set(change['generated']),set(row))
                            self.assertEqual(change['new'],json.loads(json.dumps({k:row[k] for k in change['new']},default=str)))
                            expected['gestion_joueurs.Player'].append(json.loads(json.dumps(row,default=str)))
                        self.assertEqual(json.loads(json.dumps(self.footprint(),default=str)),expected)
                        self.assertEqual(result['effects'],{'history':[],'notifications':[],'invoices':[]})
                        self.assertEqual([label for label,pk in self.signals if label!='actions.Plan'],['gestion_joueurs.Player']*2)
                        row_obj=Player.objects.get(pk=row['id']);row_obj.full_clean(exclude=['email'])
                        records.append({'mode':mode,'birth':str(birth),'plan':p['id'],'preview':change,'expected_row':json.loads(json.dumps(row,default=str)),'full_business_footprint_exact':True})
        (R/'df01-legitimate.json').write_text(json.dumps(records,indent=2))

    def test_execute_revalidates_real_derived_model_validator_without_write(self):
        field=Player._meta.get_field('age');records=[]
        with self.http() as call:
            for mode in ['create','amend']:
                step=self.step(mode,'2004-02-29')
                status,p=call('prepare',{'key':uuid.uuid4().hex,'steps':[step]});self.assertEqual(status,200,p)
                before=self.footprint();plans=list(Plan.objects.order_by('pk').values());self.signals.clear()
                approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                # Real model validator becomes stricter after approval; no engine or adapter mocking.
                with patch.object(field,'validators',[*field.validators,MinValueValidator(200)]):
                    status,body=call('execute',{'id':p['id'],'approval':approval})
                self.assertEqual(status,400,body);self.assertEqual(body,{'error':'invalid_request'})
                self.assertEqual(self.footprint(),before)
                self.assertEqual(list(Plan.objects.order_by('pk').values()),plans)
                self.assertEqual(self.signals,[])
                self.assertEqual(Plan.objects.get(pk=p['id']).state,'prepared')
                records.append({'mode':mode,'plan':p['id'],'http_status':status,'body':body,'plan_preserved':True,'business_unchanged':True})
        (R/'df01-revalidation.json').write_text(json.dumps(records,indent=2))
