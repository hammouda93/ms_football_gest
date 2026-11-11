"""Independent RED contracts; never repairs candidate or supplied harness."""
import unittest,uuid
from unittest.mock import patch
from django.db import connection
from actions.registry import catalogue
from actions.engine import Engine
from gestion_joueurs.models import Video,VideoEditor,Player
from django.contrib.auth.models import User

class IndependentCounterexamples(unittest.TestCase):
 def fixture(self):
  a=User.objects.create(username='REVIEW_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
  e=VideoEditor.objects.create(user=User.objects.create(username='REVIEW_ED_'+uuid.uuid4().hex))
  p=Player.objects.create(name='REVIEW_PLAYER',club='Fixture',league='OC',position='MF')
  return a,e,p
 def values(self,e,p):
  return dict(player=p.pk,editor=e.pk,total_payment='275.00',advance_payment='25.00',season='2025/2026',whatsapp_conversation_date='2026-12-01',deadline_from_whatsapp=False,deadline='2026-12-09',info='review')
 def test_catalogue_season_enum_does_not_advertise_model_rejected_choices(self):
  allowed={x for x,_ in Video._meta.get_field('season').choices}
  for op in ('video.conditions.create','video.conditions.amend'):
   with self.subTest(op=op):
    self.assertLessEqual(set(catalogue()[op]['schema']['season']['enum']),allowed)
 def test_nullable_editor_user_is_refused_structurally_before_preview(self):
  a,e,p=self.fixture();e.user=None;e.save()
  try:
   Engine(a.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.create','values':self.values(e,p)}])
  except (ValueError,PermissionError):return
  except Exception as exc:self.fail('Unstructured prepare exception: '+type(exc).__name__+': '+str(exc))
  self.fail('Unusable editor accepted')
 def test_amend_preview_contains_paid_and_balance_context(self):
  from test_highlights import HighlightsTests
  a,e,p=self.fixture()
  helper=HighlightsTests()
  _,pk=helper.run_action(a,'video.conditions.create',self.values(e,p))
  helper.run_action(a,'finance.highlight.payment.record',dict(video=pk,amount='50.00',payment_method='cash',payment_type='partial'))
  prepared=Engine(a.pk).prepare(uuid.uuid4().hex,[{'as':'x','op':'video.conditions.amend','values':{'id':pk,'total_payment':'310.00'}}])
  from actions.models import Plan
  x=Plan.objects.get(pk=prepared['id']).snapshots['__preview__']['changes'][0]
  from gestion_joueurs.models import Invoice,Payment
  import json
  from pathlib import Path
  paid=str(Invoice.objects.get(video_id=pk).amount_paid)
  observation={'paid':paid,'journal':[str(v) for v in Payment.objects.filter(video_id=pk).values_list('amount',flat=True)],'preview':x}
  (Path(__file__).resolve().parent/'review-financial-observation.json').write_text(json.dumps(observation,indent=2))
  self.assertEqual(paid,'75.00')
  self.assertTrue('amount_paid' in x.get('invoice',{}).get('old',{}) or 'financial' in x,'Signed price amendment preview omits actual 75.00 paid and balances; advance_payment remains 25.00')
