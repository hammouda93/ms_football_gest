"""A missing PRE now refuses the historical legitimate plan, without mutation."""
import unittest,uuid,json
from datetime import date
from actions.engine import Engine
from actions.models import Plan,Verification
from django.contrib.auth.models import User
from gestion_joueurs.models import Player
class MissingPreTests(unittest.TestCase):
 def test_missing_pre_preserves_historical_plan_and_business(self):
  actor=User.objects.create(username='FICTION_NOPRE_'+uuid.uuid4().hex,is_superuser=True)
  player=Player.objects.create(name='FICTION_NOPRE',club='BEFORE',league='OC',position='MF',date_of_birth=date(2001,1,2))
  p=Engine(actor.pk).prepare(uuid.uuid4().hex,[{'as':'p','op':'player.amend','values':{'id':player.pk,'club':'AFTER'}}])
  saved=Plan.objects.values().get(pk=p['id']);row=Player.objects.values().get(pk=player.pk)
  self.assertFalse(Verification.objects.filter(plan_id=p['id']).exists())
  with self.assertRaisesRegex(PermissionError,'verification_required'):Engine(actor.pk).execute(p['id'])
  self.assertEqual(Plan.objects.values().get(pk=p['id']),saved)
  self.assertEqual(Player.objects.values().get(pk=player.pk),row)
