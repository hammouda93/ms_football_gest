import unittest,uuid,json,hashlib
from datetime import date,timedelta
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from actions.engine import Engine
from actions.models import Plan,Verification,Audit
from gestion_joueurs.models import Player

class ScopeTests(unittest.TestCase):
 def test_plugin_manifest_declares_verify(self):
  from pathlib import Path
  text=(Path(__file__).parent/'plugin/plugin.yaml').read_text()
  self.assertIn('  - ms_football_action_verify\n',text)
 def test_verification_alias_is_configured_without_reader_reuse(self):
  from actions.mount import configure
  import os
  from unittest.mock import patch
  ns={'INSTALLED_APPS':[],'MIDDLEWARE':['django.middleware.security.SecurityMiddleware'],'DATABASES':{'default':{'ENGINE':'django.db.backends.postgresql','NAME':'FICTION','ATOMIC_REQUESTS':True,'CONN_MAX_AGE':100}}}
  with patch.dict(os.environ,{'MSF_ACTIONS_VERIFICATION_KEY':'FICTION_UNIFIED_VERIFY_KEY_001_NOT_LIVE'},clear=True):configure(ns)
  self.assertIn('verification',ns['DATABASES'])
  self.assertFalse(ns['DATABASES']['verification']['ATOMIC_REQUESTS'])
  self.assertEqual(ns['DATABASES']['verification']['CONN_MAX_AGE'],0)
  self.assertEqual(ns['ACTIONS_VERIFICATION_KEY'],'FICTION_UNIFIED_VERIFY_KEY_001_NOT_LIVE')
 def test_verify_scope_roundtrips_closed_mount(self):
  from actions.mount import _configuration,SCOPES
  self.assertIn('verify',SCOPES)
  credential={'actor':37,'scopes':['catalogue','prepare','status','verify','op:player.amend'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
  self.assertTrue(_configuration(json.dumps({'enabled':True,'credentials':{'a'*64:credential}}))['enabled'])

class PreTests(unittest.TestCase):
 def setUp(self):
  self.actor=User.objects.create(username='FICTION_US_'+uuid.uuid4().hex,is_superuser=True)
  self.player=Player.objects.create(name='FICTION_PRIVATE',club='CLUB',league='OC',position='MF',date_of_birth=date(2002,1,2))
  self.e=Engine(self.actor.pk)
  self.p=self.e.prepare(uuid.uuid4().hex,[{'as':'p','op':'player.profile.amend','values':{'id':self.player.pk,'name':'FICTION_NEW'}}])
  settings.ACTIONS_VERIFICATION_KEY='FICTION_UNIFIED_VERIFY_KEY_001_NOT_LIVE'
 def test_execute_detects_baseline_drift_outside_engine_snapshots(self):
  from actions.readback import before
  from gestion_joueurs.models import Video,VideoEditor,VideoStatusHistory
  ve=VideoEditor.objects.create(user=self.actor)
  v=Video.objects.create(player=self.player,editor=ve,status='pending',season='2025/2026',total_payment=300,advance_payment=0,deadline=date(2030,1,1))
  p=self.e.prepare(uuid.uuid4().hex,[{'as':'v','op':'video.amend','values':{'id':v.pk,'info':'FICTION_NEW'}}])
  before(self.actor.pk,p['id'])
  VideoStatusHistory.objects.filter(video=v).update(comment='UNAPPROVED_DRIFT')
  result=self.e.execute(p['id'])
  self.assertEqual((result['state'],result['error']),('failed','verification_conflict'))
  v.refresh_from_db();self.assertNotEqual(v.info,'FICTION_NEW')
 def test_stale_foreign_digest_steps_and_rollback(self):
  from actions.readback import before,after,seal
  from django.db import transaction
  import copy
  original=Plan.objects.get(pk=self.p['id'])
  t=before(self.actor.pk,self.p['id']);rec=Verification.objects.get(pk=t['receipt']);body=copy.deepcopy(rec.body)
  for change in ('expired','foreign','digest','steps'):
   rec.body=copy.deepcopy(body);rec.actor_id=self.actor.pk;rec.expires_at=timezone.datetime.fromisoformat(body['expires'])
   if change=='expired':rec.expires_at=timezone.now()-timedelta(seconds=1);rec.body['expires']=rec.expires_at.isoformat()
   if change=='foreign':rec.actor_id+=100000
   rec.mac=seal(rec.body);rec.save()
   if change=='digest':Plan.objects.filter(pk=original.pk).update(digest='0'*64)
   if change=='steps':Plan.objects.filter(pk=original.pk).update(steps=[dict(original.steps[0],values={'id':self.player.pk,'name':'TAMPER'})])
   with self.assertRaises((PermissionError,ValueError)):self.e.execute(self.p['id'])
   Plan.objects.filter(pk=original.pk).update(digest=original.digest,steps=original.steps)
  rec.actor_id=self.actor.pk;rec.body=body;rec.mac=seal(body);rec.expires_at=timezone.datetime.fromisoformat(body['expires']);rec.save()
  try:
   with transaction.atomic():
    self.assertEqual(self.e.execute(self.p['id'])['state'],'succeeded')
    raise RuntimeError('late rollback')
  except RuntimeError:pass
  self.player.refresh_from_db();self.assertEqual(self.player.name,'FICTION_PRIVATE')
  self.assertFalse(Audit.objects.filter(plan=original,event='verification_bound').exists())
  self.assertEqual(after(self.actor.pk,t)['verdict'],'not_committed')
 def test_revoked_editor_role_cannot_verify_post(self):
  from actions.readback import before,after
  from gestion_joueurs.models import Video,VideoEditor
  ve=VideoEditor.objects.create(user=self.actor)
  video=Video.objects.create(player=self.player,editor=ve,status='pending',season='2025/2026',total_payment=300,advance_payment=0,deadline=date(2030,1,1))
  p=self.e.prepare(uuid.uuid4().hex,[{'as':'v','op':'video.status.transition','values':{'id':video.pk,'status':'in_progress'}}])
  t=before(self.actor.pk,p['id']);self.e.execute(p['id'])
  self.actor.is_active=False;self.actor.save()
  with self.assertRaises(PermissionError):after(self.actor.pk,t)
 def test_pre_commit_holds_plan_lock_until_receipt_persisted(self):
  from actions.readback import before
  from unittest.mock import patch
  from django.db import connections
  from django.db.utils import OperationalError
  create=Verification.objects.create
  def checked_create(**kw):
   c=connections['verification']
   try:
    with c.cursor() as cursor:
     cursor.execute("SET lock_timeout='100ms'")
     with self.assertRaises(OperationalError):cursor.execute('SELECT id FROM actions_plan WHERE id=%s FOR UPDATE NOWAIT',[self.p['id']])
   finally:c.close()
   return create(**kw)
  with patch.object(Verification.objects,'create',side_effect=checked_create):before(self.actor.pk,self.p['id'])
 def test_post_accepts_only_the_pre_atomically_bound_to_execute(self):
  from actions.readback import before,after
  first=before(self.actor.pk,self.p['id']);second=before(self.actor.pk,self.p['id'])
  self.e.execute(self.p['id'])
  with self.assertRaisesRegex(ValueError,'verification_not_bound'):after(self.actor.pk,first)
  self.assertEqual(after(self.actor.pk,second)['verdict'],'verified')
 def test_pre_receipt_and_audit_rollback_together(self):
  from actions.readback import before
  from unittest.mock import patch
  with patch.object(Audit.objects,'create',side_effect=RuntimeError('audit persistence unavailable')):
   with self.assertRaises(RuntimeError):before(self.actor.pk,self.p['id'])
  self.assertFalse(Verification.objects.filter(plan_id=self.p['id']).exists())
 def test_verification_refusals_are_durably_audited(self):
  from actions.readback import before,after
  t=before(self.actor.pk,self.p['id'])
  rec=Verification.objects.get(pk=t['receipt']);rec.mac='0'*64;rec.save()
  with self.assertRaises(ValueError):after(self.actor.pk,t)
  self.assertTrue(Audit.objects.filter(actor_id=self.actor.pk,event='verification_refused',code='post_invalid').exists())
 def test_verification_audit_durable_and_atomic(self):
  from actions.readback import before,after
  from django.db import transaction
  t=before(self.actor.pk,self.p['id'])
  self.assertTrue(Audit.objects.filter(plan_id=self.p['id'],event='verification_pre',code=t['receipt']).exists())
  self.e.execute(self.p['id']);result=after(self.actor.pk,t)
  self.assertEqual(result['verdict'],'verified')
  self.assertTrue(Audit.objects.filter(plan_id=self.p['id'],event='verification_post',code='verified').exists())
  self.assertTrue(Audit.objects.filter(plan_id=self.p['id'],event='verification_bound',code=t['receipt']).exists())
  self.assertEqual(self.e.execute(self.p['id'])['state'],'succeeded')
  self.assertEqual(Audit.objects.filter(plan_id=self.p['id'],event='verification_bound').count(),1)
 def test_pre_refuses_stale_preconditions_and_stores_nothing(self):
  from actions.readback import before
  Player.objects.filter(pk=self.player.pk).update(club='DRIFT')
  with self.assertRaisesRegex(ValueError,'conflict'):before(self.actor.pk,self.p['id'])
  self.assertFalse(Verification.objects.filter(plan_id=self.p['id']).exists())
 def test_tampered_pre_cannot_execute(self):
  from actions.readback import before
  t=before(self.actor.pk,self.p['id'])
  rec=Verification.objects.get(pk=t['receipt']);rec.body['baseline']={};rec.save()
  with self.assertRaisesRegex(PermissionError,'verification_invalid'):self.e.execute(self.p['id'])
  self.player.refresh_from_db();self.assertEqual(self.player.name,'FICTION_PRIVATE')
 def test_execute_requires_pre_even_without_http(self):
  with self.assertRaisesRegex(PermissionError,'verification_required'):self.e.execute(self.p['id'])
  self.player.refresh_from_db();self.assertEqual(self.player.name,'FICTION_PRIVATE')
  self.assertEqual(Plan.objects.get(pk=self.p['id']).state,'prepared')
