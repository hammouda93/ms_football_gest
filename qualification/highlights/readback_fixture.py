"""Independent process, readonly exact PRE/POST, final surviving HTTP targets only."""
import json,unittest
from pathlib import Path
from django.test import override_settings
from actions import readback
from actions.models import Plan
from http_fixture import KEY
R=Path(__file__).resolve().parent
class IndependentReadback(unittest.TestCase):
 def test_committed_http_targets(self):
  receipts=[json.loads((R/n).read_bytes()) for n in json.loads((R/'FINAL-RECEIPTS.json').read_bytes())]
  latest={}
  attacks={x['id'] for x in map(json.loads,(R/'ATTACKED-TARGETS.jsonl').read_text().splitlines())}
  for r in receipts:
   p=Plan.objects.get(pk=r['plan']);pk=r['result']['results']['x']
   if pk in attacks:continue
   if pk not in latest or p.created_at>latest[pk][0].created_at:latest[pk]=(p,r)
  out=[]
  with override_settings(ACTIONS_VERIFICATION_KEY=KEY):
   for p,r in latest.values():
    # A later direct-engine tamper fixture deliberately supersedes some receipts.
    successors=Plan.objects.filter(created_at__gt=p.created_at,state='succeeded')
    if any(any(s['values'].get('id')==r['result']['results']['x'] for s in q.steps) for q in successors):continue
    verdict=readback.after(r['actor'],r['pre']);self.assertEqual(verdict['verdict'],'verified',verdict)
    # Independent ORM assertions on a fresh READ ONLY connection, not only
    # the shared PRE/POST oracle's verdict.
    from gestion_joueurs.models import Video,Invoice,Payment
    with readback.readonly():
     video=Video.objects.using('verification').get(pk=r['result']['results']['x'])
     invoice=Invoice.objects.using('verification').get(video=video)
     self.assertEqual(video.total_payment,invoice.total_amount)
     self.assertEqual(sum(Payment.objects.using('verification').filter(video=video).values_list('amount',flat=True)),invoice.amount_paid)
     self.assertEqual(str(video.whatsapp_conversation_date),'2026-12-01')
     self.assertFalse(video.automation_started);self.assertFalse(video.delivery_automation_started)
    out.append(verdict)
  self.assertGreater(len(out),0)
  (R/'INDEPENDENT-READBACK.json').write_text(json.dumps(out,indent=2))
