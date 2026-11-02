"""DS01/DS02 only: real configure/middleware/forms/views/signals, synthetic DB."""
import unittest,uuid,json,datetime,types
from pathlib import Path
from unittest.mock import patch
from django.test import Client,override_settings
from test_next import mounted,TOKEN,KEY
R=Path(__file__).resolve().parent

class FixTests(unittest.TestCase):
 def fixture(self):
  from django.contrib.auth.models import User
  from gestion_joueurs.models import Player,Video,VideoEditor,Invoice
  from client_portal.models import VideoWorkflow
  a=User.objects.create(username='FICTION_FIX_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
  e=VideoEditor.objects.create(user=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex))
  p=Player.objects.create(name='FICTION_ONLY',club='Fixture',league='OC',position='MF')
  v=Video.objects.create(player=p,editor=e,status='pending',client_portal_visible=False,total_payment='100',advance_payment='0',deadline='2026-12-01')
  Invoice.objects.create(video=v,total_amount='100',amount_paid='100',status='paid')
  VideoWorkflow.objects.create(video=v,stage='editing',progress=50)
  return a,e,v
 def values(self,e,v):return {'editor':e.pk,'video':v.pk,'amount':'20.00','salary_amount':'18.00','date':'2020-01-09','description':'FICTION','salary_paid_status':'paid'}
 def post(self,c,route,data):return c.post('/actions/v1/'+route,json.dumps(data),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
 def action(self,a,op,values,attack=None,expected='verified',execute_context=None):
  from actions.models import Plan
  from actions.http import issue_approval
  from contextlib import nullcontext
  with override_settings(**mounted(a.pk,{op})):
   c=Client();self.assertEqual(Client().get('/actions/v1/catalogue',HTTP_AUTHORIZATION='Bearer '+TOKEN).status_code,200)
   r=self.post(c,'prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':op,'values':values}]});self.assertEqual(r.status_code,200,r.content)
   p=Plan.objects.get(pk=r.json()['id']);pre=self.post(c,'verify',{'id':str(p.pk),'phase':'before'});self.assertEqual(pre.status_code,200,pre.content)
   approval=issue_approval(p.pk,a.pk,p.digest,datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=2))
   with execute_context or nullcontext():out=self.post(c,'execute',{'id':str(p.pk),'approval':approval})
   self.assertEqual(out.status_code,200,out.content)
   self.assertEqual(out.json()['state'],'failed' if expected=='not_committed' else 'succeeded',out.content)
   if attack:attack(out.json()['results']['x'])
   after=self.post(c,'verify',{'id':pre.json()['receipt'],'phase':'after'});self.assertEqual(after.status_code,200,after.content)
   self.assertEqual(after.json()['verdict'],expected,after.content)
   record={'actor':a.pk,'plan':str(p.pk),'pre':pre.json()['receipt'],'expected':expected,'immediate':after.json(),'operation':op,'values':values,'results':out.json()}
   (R/('fixed-'+str(p.pk)+'.json')).write_text(json.dumps(record,indent=2))
   return p,out.json()
 def test_ds01_encoded_access_rejected_before_preview(self):
  from actions.models import Plan
  from gestion_joueurs.models import Video
  paths=['/access/FICTION_REVIEW_TOKEN','/%61ccess/FICTION_REVIEW_TOKEN','/access%2FFICTION_REVIEW_TOKEN','/%2561ccess/FICTION_REVIEW_TOKEN','/access%252FFICTION_REVIEW_TOKEN','/%252561ccess/FICTION_REVIEW_TOKEN','/safe/%2e%2e/access/FICTION_REVIEW_TOKEN','/safe%5caccess%5cFICTION_REVIEW_TOKEN','/safe/%','/safe/%2','/safe/%GG','/safe/%FF','/safe/%C0%AFaccess','/safe/%00','/safe/%0d','/safe/%2525','/safe//final','/safe/../final']
  a,e,v=self.fixture();before=Plan.objects.count();cases=[]
  with override_settings(**mounted(a.pk,{'video.delivery.internal'})):
   for path in paths:
    with self.subTest(path=path):
     response=self.post(Client(),'prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':'video.delivery.internal','values':{'id':v.pk,'video_link':'https://example.invalid'+path}}]})
     cases.append({'path':path,'status':response.status_code,'body':response.json()})
     self.assertEqual(response.status_code,400,response.content)
  self.assertEqual(Plan.objects.count(),before);v.refresh_from_db();self.assertEqual(v.status,'pending')
  (R/'DS01-CASES.json').write_text(json.dumps(cases,indent=2))
 def test_ds01_safe_encoded_url_preserved(self):
  from gestion_joueurs.models import Video
  a,e,v=self.fixture();url='https://example.invalid/final%2Dvideo'
  p,r=self.action(a,'video.delivery.internal',{'id':v.pk,'video_link':url})
  self.assertEqual(p.steps[0]['values']['video_link'],url)
  self.assertEqual(p.snapshots['__preview__']['transitions'][0]['videoChanges']['video_link'],url)
  v.refresh_from_db();self.assertEqual(v.video_link,url)
 def test_ds02_day_changes_before_execute_conflict(self):
  from gestion_joueurs.models import Salary,Expense
  from django.db.models import DateField
  original=DateField.pre_save
  def next_day(field,instance,add):
   value=original(field,instance,add)
   if isinstance(instance,Salary) and field.name=='date':
    value+=datetime.timedelta(days=1);setattr(instance,field.attname,value)
   return value
  a,e,v=self.fixture();before=(Salary.objects.count(),Expense.objects.count())
  p,r=self.action(a,'finance.salary.record',self.values(e,v),expected='not_committed',execute_context=patch.object(DateField,'pre_save',next_day))
  self.assertEqual(r['error'],'conflict');self.assertEqual(before,(Salary.objects.count(),Expense.objects.count()))
 def test_ds02_day_changes_after_snapshot_rolls_back(self):
  from gestion_joueurs.models import Salary,Expense
  from actions.salaries import SalaryRecord
  from django.db.models import DateField
  original_field=DateField.pre_save;original_apply=SalaryRecord.apply
  def next_day(field,instance,add):
   value=original_field(field,instance,add)
   if isinstance(instance,Salary) and field.name=='date':
    value+=datetime.timedelta(days=1);setattr(instance,field.attname,value)
   return value
  def apply(adapter,*args,**kwargs):
   with patch.object(DateField,'pre_save',next_day):return original_apply(adapter,*args,**kwargs)
  a,e,v=self.fixture();before=(Salary.objects.count(),Expense.objects.count())
  self.action(a,'finance.salary.record',self.values(e,v),expected='not_committed',execute_context=patch.object(SalaryRecord,'apply',apply))
  self.assertEqual(before,(Salary.objects.count(),Expense.objects.count()))
 def test_ds02_date_changes_inside_view_rolls_back(self):
  from gestion_joueurs.models import Salary,Expense
  from gestion_joueurs.views import add_expense
  from django.db.models import DateField
  original=DateField.pre_save
  def changed(field,instance,add):
   result=original(field,instance,add)
   if isinstance(instance,Salary) and field.name=='date' and add:
    result+=datetime.timedelta(days=1);setattr(instance,field.attname,result)
   return result
  def view(*args,**kwargs):
   with patch.object(DateField,'pre_save',changed):return add_expense(*args,**kwargs)
  a,e,v=self.fixture();before=(Salary.objects.count(),Expense.objects.count())
  self.action(a,'finance.salary.record',self.values(e,v),expected='not_committed',execute_context=patch('gestion_joueurs.views.add_expense',view))
  self.assertEqual((Salary.objects.count(),Expense.objects.count()),before)
  v.refresh_from_db();self.assertEqual(v.salary_paid_status,'not_paid')
 def test_ds02_date_tamper_detected_by_post(self):
  from gestion_joueurs.models import Salary
  a,e,v=self.fixture()
  self.action(a,'finance.salary.record',self.values(e,v),attack=lambda pk:Salary.objects.filter(pk=pk).update(date='1999-01-01'),expected='mismatch')
 def test_ds02_real_auto_now_add_midnight(self):
  from gestion_joueurs.models import Salary,Expense
  instant=datetime.datetime(2026,11,2,23,30,tzinfo=datetime.timezone.utc)
  from zoneinfo import ZoneInfo
  self.assertEqual(str(instant.astimezone(ZoneInfo('Africa/Tunis')).date()),'2026-11-03')
  class DateMeta(type):
   def __instancecheck__(cls,obj):return isinstance(obj,datetime.date)
  class FrozenDate(datetime.date,metaclass=DateMeta):
   @classmethod
   def today(cls):return cls(2026,11,2)
  fields_clock=types.SimpleNamespace(date=FrozenDate,datetime=datetime.datetime)
  with patch('django.db.models.fields.datetime',fields_clock),patch('django.utils.timezone.localdate',return_value=datetime.date(2026,11,3)):
   a,e,v=self.fixture();p,r=self.action(a,'finance.salary.record',self.values(e,v))
   actual=Salary.objects.get(pk=r['results']['x']);expense=Expense.objects.get(salary=actual)
   predicted=p.snapshots['__preview__']['changes'][0]['new']['date']
   self.assertEqual(predicted,'2026-11-02');self.assertEqual(actual.date,datetime.date(2026,11,2));self.assertEqual(str(expense.date),'2020-01-09')
