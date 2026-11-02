"""Delta only; synthetic records, real mounted Django/PostgreSQL."""
import json,unittest,uuid,hashlib,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from unittest.mock import patch
from django.test import Client,override_settings
from django.conf import settings
from actions.registry import catalogue
from actions.mount import configure
R=Path(__file__).resolve().parent
NEW={'finance.highlight.payment.record','finance.performance.payment.record','finance.expense.record','finance.income.record','prospect.convert'}
TOKEN='FICTION_NEXT_BEARER';KEY='FICTION_NEXT_HMAC_NOT_HUMAN_000000000000000'

def mounted(actor,ops):
    expiry=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()
    credential={'actor':actor,'scopes':['catalogue','prepare','execute','status','verify']+['op:'+o for o in sorted(ops)],'expires':expiry,'revoked':False}
    env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR') if k in os.environ}
    env.update(MSF_ACTIONS_PILOT_CONFIG=json.dumps({'enabled':True,'credentials':{hashlib.sha256(TOKEN.encode()).hexdigest():credential}}),MSF_ACTIONS_EXECUTE_ENABLED='true',MSF_ACTIONS_APPROVAL_KEY=KEY,MSF_ACTIONS_EXECUTE_BINDING=json.dumps({'mode':'service','actor':actor,'operations':sorted(ops),'expires':expiry}),MSF_ACTIONS_VERIFICATION_KEY=KEY)
    ns={'INSTALLED_APPS':[a for a in settings.INSTALLED_APPS if a!='actions'],'MIDDLEWARE':['django.middleware.security.SecurityMiddleware'],'DATABASES':deepcopy(settings.DATABASES)}
    with patch.dict(os.environ,env,clear=True):configure(ns)
    return {k:v for k,v in ns.items() if k.startswith('ACTIONS_') or k=='MIDDLEWARE'}|{'ACTIONS_QUOTA_GLOBAL':10000,'ACTIONS_QUOTA_IDENTITY':10000}

class NextTests(unittest.TestCase):
    def test_guards_and_existing_conversion(self):
        from django.contrib.auth.models import User
        from actions.engine import Engine
        from actions.models import Plan
        from actions import readback
        from gestion_joueurs.models import Player,NonVideoIncome,Expense
        from prospects.models import Prospect
        from sportsbase_data.models import SportsBaseSubscription,PerformanceSubscriptionPayment
        a=User.objects.create(username='FICTION_GUARDS_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        e=Engine(a.pk)
        base={'category':'other','description':'FICTION','amount':'1.00','date':'2026-11-02'}
        count=NonVideoIncome.objects.count()
        ambiguous=Player.objects.create(name='FICTION_AMBIGUOUS_'+uuid.uuid4().hex,club='Fixture',league='OC',position='MF')
        Player.objects.create(name=ambiguous.name,club='Fixture',league='OC',position='MF')
        amb=Prospect.objects.create(full_name=ambiguous.name,club='Fixture',league='OC',position='midfielder',season='2026/2027',service_type='highlights')
        with self.assertRaisesRegex(ValueError,'conversion_identity_ambiguous'):e.prepare(uuid.uuid4().hex,[{'as':'x','op':'prospect.convert','values':{'id':amb.pk}}])
        future=Prospect.objects.create(full_name='FICTION_FUTURE_'+uuid.uuid4().hex,club='Fixture',league='OC',position='midfielder',date_of_birth='2099-01-01',season='2026/2027',service_type='highlights')
        with self.assertRaises(__import__('django.core.exceptions',fromlist=['ValidationError']).ValidationError):e.prepare(uuid.uuid4().hex,[{'as':'x','op':'prospect.convert','values':{'id':future.pk}}])
        for bad in ['NaN','sNaN','Infinity','0','-1','100000000000.00','1.001','bad']:
            with self.subTest(amount=bad),self.assertRaises((ValueError,__import__('django.core.exceptions',fromlist=['ValidationError']).ValidationError)):
                e.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.income.record','values':base|{'amount':bad}}])
        self.assertEqual(NonVideoIncome.objects.count(),count)
        with self.assertRaises(ValueError):e.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.expense.record','values':base|{'category':'salary'}}])
        with self.assertRaisesRegex(ValueError,'date_required'):e.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.expense.record','values':base|{'date':''}}])
        p=Player.objects.create(name='FICTION_MATCH_'+uuid.uuid4().hex,club='Fixture',league='OC',position='MF',date_of_birth=__import__('datetime').date(2000,1,1),email='preserved@example.invalid')
        pr=Prospect.objects.create(full_name=p.name,club=p.club,league='OC',position='midfielder',date_of_birth='2000-01-01',email='different@example.invalid',whatsapp_number='+21600000000',season='2026/2027',service_type='highlights')
        self.roundtrip('prospect.convert',{'id':pr.pk});pr.refresh_from_db();p.refresh_from_db();self.assertEqual(pr.player_id,p.pk);self.assertEqual(p.email,'preserved@example.invalid');self.assertEqual(p.whatsapp_number,'+21600000000')
        sub=SportsBaseSubscription.objects.create(player=p,season='2026/2027',is_active=False,total_amount='10.00')
        vals={'subscription':sub.pk,'amount':'5.00','payment_date':'2026-11-02','payment_method':'cash','reference':'','notes':''}
        steps=[{'as':'x','op':'finance.performance.payment.record','values':vals}]
        with self.assertRaises(ValueError):e.prepare(uuid.uuid4().hex,steps+[{'as':'y','op':'finance.income.record','values':base}])
        prepared=e.prepare(uuid.uuid4().hex,steps)
        with self.assertRaises(PermissionError):e.execute(prepared['id'])
        with override_settings(ACTIONS_VERIFICATION_KEY=KEY):
            readback.before(a.pk,prepared['id'])
            PerformanceSubscriptionPayment.objects.create(subscription=sub,amount='1.00',payment_method='cash')
            result=e.execute(prepared['id']);self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'conflict')
        normal=User.objects.create(username='FICTION_DENIED_'+uuid.uuid4().hex,is_active=True)
        with self.assertRaises(PermissionError):Engine(normal.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.income.record','values':base}])
        with override_settings(**mounted(a.pk,{'player.amend'})):
            c=Client();before=Plan.objects.count()
            denied=c.post('/actions/v1/prepare',json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'x','op':'finance.income.record','values':base}]}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
            self.assertEqual(denied.status_code,403);self.assertEqual(denied.json()['error'],'scope_denied');self.assertEqual(Plan.objects.count(),before)

    def test_reader_added_records(self):
        from data_access.engine import execute
        from gestion_joueurs.models import NonVideoIncome
        pk=NonVideoIncome.objects.order_by('pk').values_list('pk',flat=True).first()
        self.assertIsNotNone(pk)
        row=execute({'entity':'gestion_joueurs.nonvideoincome','select':['id','amount','category','description'],'where':{'field':'id','op':'eq','value':pk}})['rows']
        self.assertEqual(len(row),1);self.assertEqual(row[0]['id'],pk)
        from data_access.metadata import catalog
        cat=catalog();self.assertNotIn('auth.user',cat['models'])
        for entity in ['gestion_joueurs.payment','sportsbase_data.performancesubscriptionpayment','prospects.prospect']:
            result=execute({'entity':entity,'select':['id'],'orderBy':['id'],'limit':2});self.assertTrue(result['rows'])

    def test_old_contracts_and_mount_preserved(self):
        old=json.loads((R/'OLD-CONTRACTS.json').read_bytes());current=catalogue()
        predecessor=json.loads((R/'PREDECESSOR-CONTRACTS.json').read_bytes())
        self.assertEqual({k:current[k] for k in predecessor},predecessor)
        self.assertEqual({k:current[k] for k in old},old)
        from actions.mount import APPROVED_OPERATIONS
        self.assertEqual(set(current),APPROVED_OPERATIONS)
        self.assertEqual(set(current)-set(old),NEW|{'player.business.amend','organization.contact.amend','prospect.contact.amend'})
        self.assertTrue(mounted(1,set(old))['ACTIONS_ENABLED'])
        self.assertEqual(mounted(1,set(old))['MIDDLEWARE'],['django.middleware.security.SecurityMiddleware','actions.pilot.PrepareOnlyBoundary'])

    def test_highlight_end_to_end(self):
        self.assertIn('finance.highlight.payment.record',catalogue())
        from gestion_joueurs.models import Player,Video,Invoice,Payment,VideoEditor
        from django.contrib.auth.models import User
        editor=VideoEditor.objects.create(user=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex))
        p=Player.objects.create(name='FICTION_HIGHLIGHT',club='Fixture',league='OC',position='MF')
        v=Video.objects.create(player=p,editor=editor,status='pending',total_payment='100.00',advance_payment='0.00',deadline='2026-12-01')
        invoice=Invoice.objects.create(video=v,total_amount='100.00',amount_paid='10.00',status='partially_paid')
        pk=self.roundtrip('finance.highlight.payment.record',{'video':v.pk,'amount':'20.00','payment_method':'cash','payment_type':'partial'})
        payment=Payment.objects.get(pk=pk);invoice.refresh_from_db()
        self.assertEqual(payment.invoice_id,invoice.pk);self.assertEqual(str(invoice.amount_paid),'30.00');self.assertEqual(str(payment.remaining_balance),'70.00')
        from actions.engine import Engine
        a=User.objects.create(username='FICTION_OVERPAY_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        with self.assertRaisesRegex(ValueError,'overpayment'):Engine(a.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.highlight.payment.record','values':{'video':v.pk,'amount':'71.00','payment_method':'cash','payment_type':'final'}}])

    def test_conversion_end_to_end(self):
        self.assertIn('prospect.convert',catalogue())
        from prospects.models import Prospect
        from gestion_joueurs.models import Player,Video,Invoice
        prospect=Prospect.objects.create(full_name='FICTION_CONVERT_'+uuid.uuid4().hex,club='Fixture',league='OC',position='midfielder',date_of_birth='2000-01-01',email='fixture@example.invalid',whatsapp_number='+21600000000',season='2026/2027',service_type='highlights')
        before=(Video.objects.count(),Invoice.objects.count())
        pk=self.roundtrip('prospect.convert',{'id':prospect.pk})
        prospect.refresh_from_db();self.assertEqual(pk,prospect.pk);self.assertEqual(prospect.status,'converted')
        self.assertEqual(Player.objects.get(pk=prospect.player_id).position,'MF')
        self.assertEqual((Video.objects.count(),Invoice.objects.count()),before)

    def test_performance_end_to_end(self):
        self.assertIn('finance.performance.payment.record',catalogue())
        from gestion_joueurs.models import Player
        from sportsbase_data.models import SportsBaseSubscription,PerformanceSubscriptionPayment
        p=Player.objects.create(name='FICTION_PERF',club='Fixture',league='OC',position='MF')
        sub=SportsBaseSubscription.objects.create(player=p,season='2026/2027',is_active=False,total_amount='100.00',currency='EUR')
        pk=self.roundtrip('finance.performance.payment.record',{'subscription':sub.pk,'amount':'30.00','payment_date':'2026-11-02','payment_method':'bank_transfer','reference':'FICTION reference','notes':'No provider effect'})
        payment=PerformanceSubscriptionPayment.objects.get(pk=pk)
        sub.refresh_from_db()
        self.assertEqual(payment.subscription_id,sub.pk);self.assertEqual(str(sub.remaining_balance),'70.00')
        sub.refresh_from_db();self.assertFalse(sub.is_active)

    def test_expense_end_to_end(self):
        self.assertIn('finance.expense.record',catalogue())
        self.roundtrip('finance.expense.record',{'category':'Internet','description':'FICTION expense only','amount':'18.00','date':'2026-11-02'})

    def roundtrip(self,op,values):
        from django.contrib.auth.models import User
        from actions.models import Plan
        from actions.http import issue_approval
        a=User.objects.create(username='FICTION_NEXT_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        with override_settings(**mounted(a.pk,{op})):
            c=Client();h={'HTTP_AUTHORIZATION':'Bearer '+TOKEN}
            def post(route,data):return c.post('/actions/v1/'+route,json.dumps(data),content_type='application/json',**h)
            p=post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':op,'values':values}]});self.assertEqual(p.status_code,200,p.content)
            p=Plan.objects.get(pk=p.json()['id']);self.assertIn('changes',p.snapshots['__preview__'])
            pre=post('verify',{'id':str(p.pk),'phase':'before'});self.assertEqual(pre.status_code,200,pre.content)
            invalid=post('execute',{'id':str(p.pk),'approval':'FICTION invalid'})
            self.assertEqual(invalid.status_code,403);self.assertEqual(invalid.json()['error'],'approval_invalid')
            approval=issue_approval(p.pk,a.pk,p.digest,datetime.now(timezone.utc)+timedelta(minutes=2))
            r=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['state'],'succeeded',r.content)
            self.assertEqual(post('status',{'id':str(p.pk)}).json()['state'],'succeeded')
            after=post('verify',{'id':pre.json()['receipt'],'phase':'after'});self.assertEqual(after.status_code,200,after.content);self.assertEqual(after.json()['verdict'],'verified',after.content)
            repeated=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(repeated.status_code,200,repeated.content);self.assertEqual(repeated.json()['results'],r.json()['results'])
            (R/('receipt-'+str(p.pk)+'.json')).write_text(json.dumps({'plan':str(p.pk),'pre':pre.json()['receipt'],'actor':a.pk,'operation':op,'results':r.json(),'post':after.json()},indent=2))
            return r.json()['results']['x']

    def test_income_end_to_end(self):
        self.assertIn('finance.income.record',catalogue())
        from django.contrib.auth.models import User
        from gestion_joueurs.models import NonVideoIncome
        from actions.models import Plan
        from actions.http import issue_approval
        a=User.objects.create(username='FICTION_NEXT_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        values={'category':'freelance','description':'FICTION internal registration only','amount':'25.50','date':'2026-11-02'}
        with override_settings(**mounted(a.pk,{'finance.income.record'})):
            c=Client();headers={'HTTP_AUTHORIZATION':'Bearer '+TOKEN}
            def post(route,data):return c.post('/actions/v1/'+route,json.dumps(data),content_type='application/json',**headers)
            cat=c.get('/actions/v1/catalogue',**headers);self.assertEqual(cat.status_code,200,cat.content)
            before=NonVideoIncome.objects.count()
            prepared=post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'income','op':'finance.income.record','values':values}]})
            self.assertEqual(prepared.status_code,200,prepared.content);self.assertEqual(NonVideoIncome.objects.count(),before)
            p=Plan.objects.get(pk=prepared.json()['id'])
            pre=post('verify',{'id':str(p.pk),'phase':'before'});self.assertEqual(pre.status_code,200,pre.content)
            approval=issue_approval(p.pk,a.pk,p.digest,datetime.now(timezone.utc)+timedelta(minutes=2))
            result=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(result.status_code,200,result.content);self.assertEqual(result.json()['state'],'succeeded',result.content)
            status=post('status',{'id':str(p.pk)});self.assertEqual(status.json()['state'],'succeeded')
            after=post('verify',{'id':pre.json()['receipt'],'phase':'after'});self.assertEqual(after.status_code,200,after.content);self.assertEqual(after.json()['verdict'],'verified',after.content)
            obj=NonVideoIncome.objects.get(pk=result.json()['results']['income']);self.assertEqual(str(obj.amount),'25.50');self.assertEqual(obj.created_by_id,a.pk)
            (R/('receipt-'+str(p.pk)+'.json')).write_text(json.dumps({'plan':str(p.pk),'pre':pre.json()['receipt'],'actor':a.pk,'operation':'finance.income.record','results':result.json(),'post':after.json()},indent=2))
