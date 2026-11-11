import unittest,uuid,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from django.test import Client,override_settings
from http_fixture import mounted,TOKEN
from actions.registry import catalogue
R=Path(__file__).resolve().parent
class HighlightsTests(unittest.TestCase):
 def exclude_deliberate_attack(self,pk,reason):
  with (R/'ATTACKED-TARGETS.jsonl').open('a') as f:f.write(json.dumps(dict(id=pk,reason=reason))+'\n')
 def fixture(self):
  from django.contrib.auth.models import User
  from gestion_joueurs.models import Player,VideoEditor
  a=User.objects.create(username='FICTION_HL_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
  e=VideoEditor.objects.create(user=User.objects.create(username='FICTION_ED_'+uuid.uuid4().hex))
  p=Player.objects.create(name='FICTION_PLAYER',club='Fixture',league='OC',position='MF')
  return a,e,p
 def values(self,e,p):
  return dict(player=p.pk,editor=e.pk,total_payment='275.00',advance_payment='25.00',season='2025/2026',whatsapp_conversation_date='2026-12-01',deadline_from_whatsapp=False,deadline='2026-12-09',info='Exact manual terms')
 def run_action(self,a,op,v):
  from actions.models import Plan
  from actions.http import issue_approval
  with override_settings(**mounted(a.pk,{op})):
   c=Client();h={'HTTP_AUTHORIZATION':'Bearer '+TOKEN}
   def post(route,data):return c.post('/actions/v1/'+route,json.dumps(data),content_type='application/json',**h)
   self.assertEqual(c.get('/actions/v1/catalogue',**h).status_code,200)
   r=post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':op,'values':v}]})
   self.assertEqual(r.status_code,200,r.content);p=Plan.objects.get(pk=r.json()['id'])
   pre=post('verify',{'id':str(p.pk),'phase':'before'});self.assertEqual(pre.status_code,200,pre.content)
   approval=issue_approval(p.pk,a.pk,p.digest,datetime.now(timezone.utc)+timedelta(minutes=2))
   r=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['state'],'succeeded',r.content)
   result=r.json();postread=post('verify',{'id':pre.json()['receipt'],'phase':'after'})
   self.assertEqual(postread.status_code,200,postread.content);self.assertEqual(postread.json()['verdict'],'verified',postread.content)
   replay=post('execute',{'id':str(p.pk),'approval':approval});self.assertEqual(replay.json()['results'],result['results'])
   self.assertEqual(post('status',{'id':str(p.pk)}).json()['state'],'succeeded')
   (R/('hl-'+str(p.pk)+'.json')).write_text(json.dumps(dict(actor=a.pk,plan=str(p.pk),pre=pre.json()['receipt'],result=result,post=postread.json()),indent=2))
   return p,result['results']['x']
 def test_create_exact_direct_terms_and_advance(self):
  self.assertIn('video.conditions.create',catalogue())
  from gestion_joueurs.models import Video,Invoice,Payment
  a,e,p=self.fixture();plan,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  v=Video.objects.get(pk=pk);i=Invoice.objects.get(video=v);pay=Payment.objects.get(video=v)
  self.assertEqual(str(v.total_payment),'275.00');self.assertEqual(str(v.deadline),'2026-12-09');self.assertEqual(str(v.whatsapp_conversation_date),'2026-12-01')
  self.assertEqual(str(i.amount_paid),'25.00');self.assertEqual(i.status,'partially_paid');self.assertEqual(str(pay.amount),'25.00')
  self.assertEqual(len(plan.snapshots['__preview__']['changes'][0]['notifications']),1)
 def test_amend_terms_editor_and_invoice_preserves_old_payments(self):
  self.assertIn('video.conditions.amend',catalogue())
  from gestion_joueurs.models import Video,Invoice,Payment,VideoEditor
  from django.contrib.auth.models import User
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  old=list(Payment.objects.filter(video_id=pk).values())
  editor=VideoEditor.objects.create(user=User.objects.create(username='FICTION_NEW_'+uuid.uuid4().hex))
  plan,_=self.run_action(a,'video.conditions.amend',dict(id=pk,total_payment='310.00',editor=editor.pk,deadline='2026-12-13',info='new exact terms'))
  v=Video.objects.get(pk=pk);i=Invoice.objects.get(video=v)
  self.assertEqual(v.editor_id,editor.pk);self.assertEqual(str(v.deadline),'2026-12-13');self.assertEqual(str(i.total_amount),'310.00');self.assertEqual(str(i.amount_paid),'25.00')
  self.assertEqual(list(Payment.objects.filter(video_id=pk).values()),old)
  self.assertEqual(len(plan.snapshots['__preview__']['changes'][0]['notifications']),1)
  plan,_=self.run_action(a,'video.conditions.amend',dict(id=pk,info='info only no reassignment'))
  self.assertEqual(plan.snapshots['__preview__']['changes'][0]['notifications'],[])
 def test_old_payment_drift_refused_before_apply(self):
  from actions.engine import Engine
  from actions import readback
  from gestion_joueurs.models import Payment
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  engine=Engine(a.pk)
  with override_settings(ACTIONS_VERIFICATION_KEY='FICTION_DRIFT_0000000000000000000000000000'):
   plan=engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='must not apply')}])
   readback.before(a.pk,plan['id'])
   Payment.objects.filter(video_id=pk).update(amount='26.00')
   self.exclude_deliberate_attack(pk,'payment drift before execution')
   result=engine.execute(plan['id']);self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'conflict')
 def test_package_exact_price_automatic_deadline_and_boundaries(self):
  from actions.engine import Engine
  from client_portal.models import Organization
  from gestion_joueurs.models import Video
  a,e,p=self.fixture();org=Organization.objects.create(name='FICTION ACADEMY',kind='academy',is_active=True)
  values=self.values(e,p)|dict(client_organization=org.pk,match_package=3,total_payment='300.00',advance_payment='0.00',deadline_from_whatsapp=True,deadline='2026-12-06')
  _,pk=self.run_action(a,'video.conditions.create',values)
  self.assertEqual(Video.objects.get(pk=pk).match_package,3)
  for name,bad in [('total_payment','350.00'),('deadline','2026-12-09'),('season','2026/2027'),('advance_payment','NaN'),('advance_payment','301.00'),('match_package',4)]:
   # Distinct player avoids duplicate-order masking of the invalid boundary.
   b,ed,pl=self.fixture();vals=values|dict(player=pl.pk,editor=ed.pk)|{name:bad}
   with self.subTest(field=name),self.assertRaises(ValueError):Engine(b.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.create','values':vals}])
 def test_permissions_scopes_pre_and_composition_refusal(self):
  from actions.engine import Engine
  from django.contrib.auth.models import User
  from actions.models import Plan
  a,e,p=self.fixture();v=self.values(e,p);steps=[{'as':'x','op':'video.conditions.create','values':v}]
  normal=User.objects.create(username='FICTION_NORMAL_'+uuid.uuid4().hex)
  with self.assertRaises(PermissionError):Engine(normal.pk).prepare(uuid.uuid4().hex,steps)
  with override_settings(**mounted(a.pk,{'video.amend'})):
   n=Plan.objects.count();r=Client().post('/actions/v1/prepare',json.dumps(dict(key=uuid.uuid4().hex,steps=steps)),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
   self.assertEqual(r.status_code,403);self.assertEqual(r.json()['error'],'scope_denied');self.assertEqual(Plan.objects.count(),n)
  with self.assertRaisesRegex(ValueError,'plan_dependency_not_simulable'):Engine(a.pk).prepare(uuid.uuid4().hex,steps+[{'as':'y','op':'player.amend','values':dict(id=p.pk,club='X')}])
  plan=Engine(a.pk).prepare(uuid.uuid4().hex,steps)
  with self.assertRaisesRegex(PermissionError,'verification_required'):Engine(a.pk).execute(plan['id'])
 def test_amend_post_detects_old_payment_tampering(self):
  from actions.engine import Engine
  from actions import readback
  from gestion_joueurs.models import Payment
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  with override_settings(ACTIONS_VERIFICATION_KEY='FICTION_POST_0000000000000000000000000000'):
   engine=Engine(a.pk);plan=engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='POST exact')}])
   ticket=readback.before(a.pk,plan['id']);self.assertEqual(engine.execute(plan['id'])['state'],'succeeded')
   self.assertEqual(readback.after(a.pk,ticket)['verdict'],'verified')
   Payment.objects.filter(video_id=pk).update(amount='900.00')
   self.exclude_deliberate_attack(pk,'payment tamper after successful POST')
   self.assertEqual(readback.after(a.pk,ticket)['verdict'],'mismatch')
 def test_package_amend_reconciles_invoice_exactly(self):
  from gestion_joueurs.models import Video,Invoice
  from client_portal.models import Organization
  a,e,p=self.fixture();org=Organization.objects.create(name='FICTION PACKAGE',kind='academy')
  vals=self.values(e,p)|dict(client_organization=org.pk,match_package=3,total_payment='300.00')
  _,pk=self.run_action(a,'video.conditions.create',vals)
  _,_=self.run_action(a,'video.conditions.amend',dict(id=pk,match_package=5,total_payment='350.00'))
  self.assertEqual(Video.objects.get(pk=pk).match_package,5);self.assertEqual(str(Invoice.objects.get(video_id=pk).total_amount),'350.00')
 def test_existing_contracts_and_lifecycle_preserved(self):
  import hashlib
  from actions.mount import APPROVED_OPERATIONS
  old=json.loads((R/'BASE-CONTRACTS.json').read_text())
  self.assertEqual({k:catalogue()[k] for k in old},old);self.assertEqual(set(catalogue()),APPROVED_OPERATIONS)
  from gestion_joueurs.models import Video,Invoice
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  _,_=self.run_action(a,'video.status.transition',dict(id=pk,status='in_progress'))
  _,_=self.run_action(a,'video.delivery.internal',dict(id=pk,video_link='https://example.invalid/final'))
  self.assertEqual(Video.objects.get(pk=pk).status,'delivered');self.assertEqual(str(Invoice.objects.get(video_id=pk).amount_paid),'25.00')
 def test_history_inconsistent_refused_before_amend(self):
  from actions.engine import Engine
  from gestion_joueurs.models import VideoStatusHistory
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  VideoStatusHistory.objects.filter(video_id=pk).update(status='completed')
  self.exclude_deliberate_attack(pk,'history tamper')
  with self.assertRaisesRegex(ValueError,'history_status_conflict'):
   Engine(a.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='not a transition')}])
 def test_initial_payment_variants_and_no_external_effects(self):
  from gestion_joueurs.models import Invoice,Payment,Notification,VideoStatusHistory
  from client_portal.models import CommunicationLog
  from django.core import mail
  mail.get_connection();before=len(mail.outbox);com=CommunicationLog.objects.count()
  for advance,status,payment_count in [('0.00','unpaid',0),('275.00','paid',1)]:
   a,e,p=self.fixture();plan,pk=self.run_action(a,'video.conditions.create',self.values(e,p)|dict(advance_payment=advance))
   i=Invoice.objects.get(video_id=pk);self.assertEqual(i.status,status);self.assertEqual(Payment.objects.filter(video_id=pk).count(),payment_count)
   self.assertEqual(Notification.objects.filter(video_id=pk).count(),len(plan.snapshots['__preview__']['changes'][0]['notifications']))
   self.assertEqual(VideoStatusHistory.objects.filter(video_id=pk).count(),1)
  self.assertEqual(len(mail.outbox),before);self.assertEqual(CommunicationLog.objects.count(),com)
 def test_idempotency_integrity_pre_expiry_and_amend_money_boundaries(self):
  from actions.engine import Engine
  from actions import readback
  from actions.models import Plan,Verification
  from django.utils import timezone as tz
  a,e,p=self.fixture();_,pk=self.run_action(a,'video.conditions.create',self.values(e,p))
  engine=Engine(a.pk);steps=[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='sealed text')}];key=uuid.uuid4().hex
  p1=engine.prepare(key,steps);self.assertEqual(engine.prepare(key,steps)['id'],p1['id'])
  with self.assertRaisesRegex(ValueError,'idempotency_mismatch'):engine.prepare(key,[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='other')}])
  for values in [dict(id=pk,advance_payment='27.00'),dict(id=pk,total_payment='-1'),dict(id=pk,total_payment='sNaN'),dict(id=pk,total_payment='1.001'),dict(id=pk),dict(id=pk,season='2026/2027')]:
   with self.subTest(values=values),self.assertRaises(ValueError):engine.prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.amend','values':values}])
  with override_settings(ACTIONS_VERIFICATION_KEY='FICTION_INTEGRITY_00000000000000000000000000'):
   ticket=readback.before(a.pk,p1['id']);rec=Verification.objects.get(pk=ticket['receipt'])
   # Properly sealed but expired PRE cannot authorize a mutation.
   rec.body['expires']=(tz.now()-timedelta(seconds=1)).isoformat();rec.expires_at=rec.body['expires'];rec.mac=readback.seal(rec.body);rec.save()
   with self.assertRaisesRegex(PermissionError,'verification_invalid'):engine.execute(p1['id'])
   Plan.objects.filter(pk=p1['id']).update(digest='0'*64)
   with self.assertRaisesRegex(ValueError,'plan_integrity'):engine.execute(p1['id'])
