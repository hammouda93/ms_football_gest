import unittest,uuid,json
from pathlib import Path
from django.test import override_settings
from test_next import mounted,TOKEN,KEY
from actions.registry import catalogue
R=Path(__file__).resolve().parent

class DeliverySalaryTests(unittest.TestCase):
 def fixture(self):
  from django.contrib.auth.models import User
  from gestion_joueurs.models import Player,Video,VideoEditor,Invoice
  from client_portal.models import VideoWorkflow
  a=User.objects.create(username='FICTION_DS_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
  editor=VideoEditor.objects.create(user=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex))
  p=Player.objects.create(name='FICTION_ONLY',club='Fixture',league='OC',position='MF')
  v=Video.objects.create(player=p,editor=editor,status='pending',client_portal_visible=False,total_payment='100',advance_payment='0',deadline='2026-12-01')
  Invoice.objects.create(video=v,total_amount='100',amount_paid='100',status='paid')
  VideoWorkflow.objects.create(video=v,stage='editing',progress=50)
  return a,editor,v
 def run_action(self,a,op,values,attack=None,conflict=None):
  from django.test import Client
  from actions.models import Plan
  from actions.http import issue_approval
  from datetime import datetime,timedelta,timezone
  with override_settings(**mounted(a.pk,{op})):
   c=Client();h={'HTTP_AUTHORIZATION':'Bearer '+TOKEN}
   def post(route,data):return c.post('/actions/v1/'+route,json.dumps(data),content_type='application/json',**h)
   cat=c.get('/actions/v1/catalogue',**h);self.assertEqual(cat.status_code,200,cat.content)
   p=post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':op,'values':values}]});self.assertEqual(p.status_code,200,p.content)
   p=Plan.objects.get(pk=p.json()['id'])
   pre=post('verify',{'id':str(p.pk),'phase':'before'});self.assertEqual(pre.status_code,200,pre.content)
   if conflict:conflict()
   approval=issue_approval(p.pk,a.pk,p.digest,datetime.now(timezone.utc)+timedelta(minutes=2))
   invalid=post('execute',{'id':str(p.pk),'approval':'FICTION_INVALID'});self.assertEqual(invalid.status_code,403)
   result=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(result.status_code,200,result.content)
   self.assertEqual(result.json()['state'],'failed' if conflict else 'succeeded',result.content)
   self.assertEqual(post('status',{'id':str(p.pk)}).json()['state'],result.json()['state'])
   if attack:attack(result.json()['results']['x'])
   postread=post('verify',{'id':pre.json()['receipt'],'phase':'after'});self.assertEqual(postread.status_code,200,postread.content)
   self.assertEqual(postread.json()['verdict'],'not_committed' if conflict else 'mismatch' if attack else 'verified',postread.content)
   repeated=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(repeated.json()['results'],result.json()['results'])
   record={'actor':a.pk,'plan':str(p.pk),'pre':pre.json()['receipt'],'verdict':postread.json()['verdict'],'operation':op,'results':result.json()}
   (R/('ds-'+str(p.pk)+'.json')).write_text(json.dumps(record,indent=2))
   return p,result.json()
 def test_delivery(self):
  self.assertIn('video.delivery.internal',catalogue())
  from gestion_joueurs.models import Video,VideoStatusHistory
  from client_portal.models import CommunicationLog,VideoWorkflow
  from django.core import mail
  mail.get_connection()
  a,e,v=self.fixture();com=CommunicationLog.objects.count()
  p,result=self.run_action(a,'video.delivery.internal',{'id':v.pk,'video_link':'https://example.invalid/final'})
  v.refresh_from_db();self.assertEqual(v.status,'delivered');self.assertTrue(v.delivery_date)
  self.assertFalse(v.client_portal_visible);self.assertFalse(v.delivery_automation_completed)
  self.assertEqual(VideoStatusHistory.objects.filter(video=v,status='delivered').count(),1)
  self.assertEqual(CommunicationLog.objects.count(),com);self.assertEqual(len(mail.outbox),0)
  self.assertIn('portal',p.snapshots['__preview__']['transitions'][0])
  self.assertEqual(VideoWorkflow.objects.get(video=v).stage,'delivered')
 def test_guards_conflicts_and_tamper(self):
  from actions.engine import Engine
  from actions.models import Plan
  from gestion_joueurs.models import Salary,Expense,Video,Invoice
  from django.test import Client
  a,e,v=self.fixture();engine=Engine(a.pk)
  values={'editor':e.pk,'video':v.pk,'amount':'20.00','salary_amount':'18.00','date':'2026-11-02','description':'FICTION','salary_paid_status':'paid'}
  for n,bad in [('salary_amount','NaN'),('amount','-1'),('date',''),('salary_paid_status','arbitrary'),('editor',e.pk+999999)]:
   with self.subTest(field=n),self.assertRaises(Exception):engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.salary.record','values':values|{n:bad}}])
  other_a,other_e,other_v=self.fixture()
  with self.assertRaisesRegex(ValueError,'salary_editor_video_mismatch'):engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.salary.record','values':values|{'editor':other_e.pk}}])
  with self.assertRaisesRegex(ValueError,'plan_dependency_not_simulable'):engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.salary.record','values':values},{'as':'y','op':'video.amend','values':{'id':v.pk,'info':'x'}}])
  for url in ['https://example.invalid/final?token=FICTION','https://user:FICTION@example.invalid/final','https://example.invalid/access/FICTION','javascript:alert(1)','']:
   with self.subTest(url=url),self.assertRaises((ValueError,PermissionError)):engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'video.delivery.internal','values':{'id':v.pk,'video_link':url}}])
  before=(Salary.objects.count(),Expense.objects.count())
  with override_settings(**mounted(a.pk,{'player.amend'})):
   response=Client().post('/actions/v1/prepare',json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'x','op':'finance.salary.record','values':values}]}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
   self.assertEqual(response.status_code,403);self.assertEqual(response.json()['error'],'scope_denied')
  self.assertEqual((Salary.objects.count(),Expense.objects.count()),before)
  self.run_action(a,'finance.salary.record',values,conflict=lambda:Video.objects.filter(pk=v.pk).update(salary_paid_status='partially_paid'))
  a,e,v=self.fixture();values=values|{'editor':e.pk,'video':v.pk}
  old=Salary.objects.create(user_id=e.user_id,video=v,amount='7',created_by=a)
  expense=Expense.objects.create(salary=old,category='salary',amount='7',date='2026-11-02',created_by=a)
  self.run_action(a,'finance.salary.record',values,attack=lambda pk:Salary.objects.filter(pk=old.pk).update(amount='70'))
  a,e,v=self.fixture();values=values|{'editor':e.pk,'video':v.pk}
  old=Salary.objects.create(user_id=e.user_id,video=v,amount='7',created_by=a)
  expense=Expense.objects.create(salary=old,category='salary',amount='7',date='2026-11-02',created_by=a)
  self.run_action(a,'finance.salary.record',values,attack=lambda pk:Expense.objects.filter(pk=expense.pk).update(amount='70'))
  a,e,v=self.fixture()
  self.run_action(a,'video.delivery.internal',{'id':v.pk,'video_link':'https://example.invalid/final'},conflict=lambda:Invoice.objects.filter(video=v).update(amount_paid='50'))
  a,e,v=self.fixture()
  self.run_action(a,'video.delivery.internal',{'id':v.pk,'video_link':'https://example.invalid/final'},attack=lambda pk:Video.objects.filter(pk=pk).update(client_portal_visible=True))

 def test_preservation_reader_and_protocol(self):
  from actions.engine import Engine
  from actions import readback
  from actions.models import Plan
  from actions.mount import APPROVED_OPERATIONS
  from gestion_joueurs.models import Salary,Expense
  from data_access.engine import execute
  from data_access.metadata import catalog
  import hashlib
  provenance=json.loads((R/'PROVENANCE.json').read_bytes());base=Path(provenance['base'])
  current=catalogue()
  self.assertEqual(len(current),24);self.assertEqual(set(current),APPROVED_OPERATIONS)
  for f,h in provenance['baseSources'].items():
   if f.startswith('data_access/') or not f.startswith('actions/'):
    self.assertEqual(hashlib.sha256((R/'source'/f).read_bytes()).hexdigest(),h)
  # Metadata-only old catalogue captured in a distinct process, without repeating effects.
  old=json.loads((R/'BASE-CONTRACTS.json').read_bytes())
  self.assertEqual(len(old),22);self.assertEqual({k:current[k] for k in old},old)
  self.assertTrue(mounted(1,set(old))['ACTIONS_ENABLED'])
  cat=catalog();self.assertEqual(len(cat['models']),37)
  self.assertEqual(sum(len(m['fields']) for m in cat['models'].values()),385)
  a,e,v=self.fixture();engine=Engine(a.pk)
  vals={'editor':e.pk,'video':v.pk,'amount':'20.00','salary_amount':'18.00','date':'2026-11-02','description':'FICTION','salary_paid_status':'paid'}
  p=engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'finance.salary.record','values':vals}]);before=(Salary.objects.count(),Expense.objects.count())
  with self.assertRaisesRegex(PermissionError,'verification_required'):engine.execute(p['id'])
  self.assertEqual(before,(Salary.objects.count(),Expense.objects.count()))
  _,result=self.run_action(a,'finance.salary.record',vals)
  rows=execute({'entity':'gestion_joueurs.salary','select':['id','amount'],'where':{'field':'id','op':'eq','value':result['results']['x']}})['rows']
  self.assertEqual(len(rows),1)

 def test_salary_journal_and_status_attacks(self):
  from gestion_joueurs.models import Salary,Expense,Video
  for mode in ('salary_delete','salary_insert','expense_delete','expense_insert','status'):
   with self.subTest(mode=mode):
    a,e,v=self.fixture()
    old=Salary.objects.create(user_id=e.user_id,video=v,amount='7',created_by=a)
    exp=Expense.objects.create(salary=old,category='salary',amount='7',date='2026-11-02',created_by=a)
    values={'editor':e.pk,'video':v.pk,'amount':'20.00','salary_amount':'18.00','date':'2026-11-02','description':'FICTION','salary_paid_status':'paid'}
    def attack(pk):
     if mode=='salary_delete':Salary.objects.filter(pk=old.pk).delete()
     elif mode=='salary_insert':Salary.objects.create(user_id=e.user_id,video=v,amount='99',created_by=a)
     elif mode=='expense_delete':Expense.objects.filter(pk=exp.pk).delete()
     elif mode=='expense_insert':Expense.objects.create(salary=old,category='salary',amount='99',date='2026-11-02',created_by=a)
     else:Video.objects.filter(pk=v.pk).update(salary_paid_status='not_paid')
    self.run_action(a,'finance.salary.record',values,attack=attack)

 def test_delivery_variants(self):
  from gestion_joueurs.models import Invoice,VideoStatusHistory
  from client_portal.models import VideoWorkflow
  from actions.engine import Engine
  for balance,visible,workflow in ((50,True,True),(0,True,False)):
   a,e,v=self.fixture();v.client_portal_visible=visible;v.delivery_date=__import__('datetime').date(2020,1,1);v.save(update_fields=['client_portal_visible','delivery_date'])
   Invoice.objects.filter(video=v).update(amount_paid=str(100-balance))
   if not workflow:VideoWorkflow.objects.filter(video=v).delete()
   p,r=self.run_action(a,'video.delivery.internal',{'id':v.pk,'video_link':'https://example.invalid/final'})
   x=p.snapshots['__preview__']['transitions'][0];self.assertEqual(x['portal']['final_available_after'],balance==0)
   v.refresh_from_db();self.assertTrue(v.client_portal_visible);self.assertEqual(str(v.delivery_date),'2020-01-01')
   self.assertTrue(VideoStatusHistory.objects.filter(video=v,status='delivered').exists())
   with self.assertRaisesRegex(ValueError,'already_delivered'):Engine(a.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'video.delivery.internal','values':{'id':v.pk,'video_link':'https://example.invalid/final'}}])

 def test_salary(self):
  self.assertIn('finance.salary.record',catalogue())
  from gestion_joueurs.models import Salary,Expense
  a,e,v=self.fixture()
  p,result=self.run_action(a,'finance.salary.record',{'editor':e.pk,'video':v.pk,'amount':'20.00','salary_amount':'18.00','date':'2026-11-02','description':'FICTION independent expense/salary amounts','salary_paid_status':'partially_paid'})
  salary=Salary.objects.get(pk=result['results']['x']);expense=Expense.objects.get(salary=salary)
  self.assertEqual(salary.user_id,e.user_id);self.assertEqual(str(salary.amount),'18.00');self.assertEqual(str(expense.amount),'20.00')
  v.refresh_from_db();self.assertEqual(v.salary_paid_status,'partially_paid')
  self.assertEqual(p.snapshots['__preview__']['changes'][0]['currency'],'TND')
