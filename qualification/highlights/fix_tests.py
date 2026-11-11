"""Targeted acceptance strengthening independent HL-01/02/03 probes."""
import json,uuid,unittest
from pathlib import Path
from decimal import Decimal
from django.test import Client,override_settings
import test_highlights as acceptance
from http_fixture import mounted,TOKEN

class FixTests(unittest.TestCase):
 def test_hl01_exact_signed_financial_projection_and_preserved_payments(self):
  from actions.models import Plan
  from gestion_joueurs.models import Invoice,Payment,Video
  h=acceptance.HighlightsTests();a,e,p=h.fixture()
  _,pk=h.run_action(a,'video.conditions.create',h.values(e,p))
  h.run_action(a,'finance.highlight.payment.record',dict(video=pk,amount='50.00',payment_method='cash',payment_type='partial'))
  payments=list(Payment.objects.filter(video_id=pk).order_by('pk').values())
  expected_old=dict(total_amount='275.00',amount_paid='75.00',payment_journal_total='75.00',remaining_balance='200.00',status='partially_paid')
  observations=[]
  # Same real ledger, including a price below paid: preserve actual signed balance, no clipping.
  for price,balance,status in [('310.00','235.00','partially_paid'),('75.00','0.00','paid'),('60.00','-15.00','paid')]:
   with self.subTest(price=price):
    with override_settings(**mounted(a.pk,{'video.conditions.amend'})):
     response=Client().post('/actions/v1/prepare',json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,total_payment=price)}]}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
    self.assertEqual(response.status_code,200,response.content)
    x=response.json()['preview']['changes'][0]
    self.assertEqual(x,Plan.objects.get(pk=response.json()['id']).snapshots['__preview__']['changes'][0])
    self.assertEqual(x['currency'],'TND')
    self.assertEqual(x.get('financial',{}).get('old'),expected_old)
    self.assertEqual(x['financial']['new'],expected_old|dict(total_amount=price,remaining_balance=balance,status=status))
    self.assertEqual(x['invoice']['old'],{k:v for k,v in expected_old.items() if k not in ('payment_journal_total','remaining_balance')})
    self.assertEqual(x['invoice']['new'],x['invoice']['old']|dict(total_amount=price,status=status))
    self.assertEqual(x['new']['advance_payment'],'25.00')
    self.assertEqual(list(Payment.objects.filter(video_id=pk).order_by('pk').values()),payments)
    self.assertEqual(str(Invoice.objects.get(video_id=pk).total_amount),'275.00')
    observations.append(x)
  h.run_action(a,'video.conditions.amend',dict(id=pk,total_payment='310.00'))
  i=Invoice.objects.get(video_id=pk)
  self.assertEqual((str(i.total_amount),str(i.amount_paid),i.status),('310.00','75.00','partially_paid'))
  self.assertEqual(list(Payment.objects.filter(video_id=pk).order_by('pk').values()),payments)
  (Path(__file__).resolve().parent/'FIX-FINANCIAL.json').write_text(json.dumps(dict(video=pk,previews=observations,payments_preserved=True),indent=2))

 def test_hl03_real_http_refuses_nullable_editor_before_preview_without_business_writes(self):
  from actions.models import Plan
  from gestion_joueurs.models import VideoEditor,Video,Invoice,Payment,Notification,VideoStatusHistory
  h=acceptance.HighlightsTests();a,e,p=h.fixture()
  _,pk=h.run_action(a,'video.conditions.create',h.values(e,p))
  bad=VideoEditor.objects.create(user=None)
  _,_,new_player=h.fixture()
  observations=[]
  for op,values in [('video.conditions.create',h.values(bad,new_player)),('video.conditions.amend',dict(id=pk,editor=bad.pk))]:
   with self.subTest(op=op):
    models=[Video,Invoice,Payment,Notification,VideoStatusHistory,Plan]
    before=[list(m.objects.order_by('pk').values()) for m in models]
    with override_settings(**mounted(a.pk,{op})):
     r=Client(raise_request_exception=False).post('/actions/v1/prepare',json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'x','op':op,'values':values}]}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
    self.assertEqual(r.status_code,400,r.content[:500])
    self.assertEqual(r.json(),{'error':'invalid_request'})
    self.assertEqual(r['Cache-Control'],'no-store')
    self.assertEqual([list(m.objects.order_by('pk').values()) for m in models],before)
    observations.append(dict(op=op,status=r.status_code,body=r.json()))
  # A legacy row with the same nullable editor must also fail for an info-only amendment.
  Video.objects.filter(pk=pk).update(editor=bad)
  with override_settings(**mounted(a.pk,{'video.conditions.amend'})):
   r=Client(raise_request_exception=False).post('/actions/v1/prepare',json.dumps({'key':uuid.uuid4().hex,'steps':[{'as':'x','op':'video.conditions.amend','values':dict(id=pk,info='legacy null editor')}]}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+TOKEN)
  self.assertEqual(r.status_code,400,r.content[:500]);self.assertEqual(r.json(),{'error':'invalid_request'})
  # Restore test-owned row only, so independent readback can verify the successful create receipt.
  Video.objects.filter(pk=pk).update(editor=e)
  (Path(__file__).resolve().parent/'FIX-HTTP.json').write_text(json.dumps(observations,indent=2))
