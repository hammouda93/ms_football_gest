"""Independent readback: explicit supersession of create by later payment."""
import json,unittest
from pathlib import Path
from django.test import override_settings
from actions.models import Plan
from actions import readback
from http_fixture import KEY
R=Path(__file__).resolve().parent
names=[];superseded=[]
for p in R.glob('hl-*.json'):
 r=json.loads(p.read_text());plan=Plan.objects.get(pk=r['plan'])
 if not plan.steps[0]['op'].startswith('video.'):continue
 pk=r['result']['results']['x']
 payments=[q for q in Plan.objects.filter(created_at__gt=plan.created_at,state='succeeded').order_by('created_at') if any(s['op']=='finance.highlight.payment.record' and s['values'].get('video')==pk for s in q.steps)]
 if payments:superseded.append(dict(receipt=p.name,video=pk,payment_plans=[str(q.pk) for q in payments]))
 else:names.append(p.name)
(R/'FINAL-RECEIPTS.json').write_text(json.dumps(sorted(names)))
(R/'SUPERSEDED-CREATE-RECEIPTS.json').write_text(json.dumps(superseded,indent=2))
from readback_fixture import IndependentReadback
class PaymentSuccessors(unittest.TestCase):
 def test_latest_payment_and_persisted_ledger_for_superseded_creates(self):
  from gestion_joueurs.models import Video,Invoice,Payment
  observations=[]
  for x in superseded:
   pk=x['video']
   amendments=[q for q in Plan.objects.filter(state='succeeded') if any(s['op']=='video.conditions.amend' and s['values'].get('id')==pk for s in q.steps)]
   if not amendments:
    plan=Plan.objects.get(pk=x['payment_plans'][-1]);r=json.loads((R/('hl-'+str(plan.pk)+'.json')).read_text())
    with override_settings(ACTIONS_VERIFICATION_KEY=KEY):self.assertEqual(readback.after(r['actor'],r['pre'])['verdict'],'verified')
   with readback.readonly():
    v=Video.objects.using('verification').get(pk=pk);i=Invoice.objects.using('verification').get(video_id=pk)
    amounts=list(Payment.objects.using('verification').filter(video_id=pk).order_by('pk').values_list('amount',flat=True))
    self.assertEqual([str(a) for a in amounts],['25.00','50.00']);self.assertEqual(str(i.amount_paid),'75.00');self.assertEqual(v.total_payment,i.total_amount)
    self.assertEqual(str(i.total_amount),'310.00' if amendments else '275.00')
   observations.append(dict(video=pk,amounts=list(map(str,amounts)),paid=str(i.amount_paid),price=str(i.total_amount)))
  self.assertEqual(len(observations),2)
  (R/'FIX-INDEPENDENT-LEDGERS.json').write_text(json.dumps(observations,indent=2))
