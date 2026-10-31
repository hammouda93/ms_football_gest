"""Real PostgreSQL order and fail-closed PRE regression probes."""
import unittest,uuid
from datetime import date,timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import connections
from django.db.utils import OperationalError
from django.utils import timezone
from actions.engine import Engine
from actions.models import Plan,Verification,Audit
from actions.readback import before,seal
from gestion_joueurs.models import Player

class OrderingTests(unittest.TestCase):
 def setUp(self):
  self.actor=User.objects.create(username='FICTION_ORDER_'+uuid.uuid4().hex,is_superuser=True)
  self.player=Player.objects.create(name='FICTION_ORDER',club='BEFORE',league='OC',position='MF',date_of_birth=date(2001,1,2))
  self.e=Engine(self.actor.pk)
  self.p=self.e.prepare(uuid.uuid4().hex,[{'as':'p','op':'player.amend','values':{'id':self.player.pk,'club':'AFTER'}}])
 def unchanged(self,code,exception):
  p=Plan.objects.values().get(pk=self.p['id']);row=Player.objects.values().get(pk=self.player.pk)
  audit=Audit.objects.count()
  with self.assertRaisesRegex(exception,'^'+code+'$'):self.e.execute(self.p['id'])
  self.assertEqual(Plan.objects.values().get(pk=self.p['id']),p)
  self.assertEqual(Player.objects.values().get(pk=self.player.pk),row)
  self.assertEqual(Audit.objects.count(),audit)
 def test_integrity_precedes_missing_pre(self):
  Plan.objects.filter(pk=self.p['id']).update(digest='0'*64)
  self.unchanged('plan_integrity',ValueError)
 def test_integrity_precedes_invalid_pre(self):
  t=before(self.actor.pk,self.p['id'])
  Verification.objects.filter(pk=t['receipt']).update(mac='0'*64)
  Plan.objects.filter(pk=self.p['id']).update(digest='0'*64)
  self.unchanged('plan_integrity',ValueError)
 def test_intact_plan_still_requires_pre(self):self.unchanged('verification_required',PermissionError)
 def test_invalid_pre_still_refused(self):
  t=before(self.actor.pk,self.p['id']);Verification.objects.filter(pk=t['receipt']).update(mac='0'*64)
  self.unchanged('verification_invalid',PermissionError)
 def test_expired_pre_still_refused(self):
  t=before(self.actor.pk,self.p['id']);r=Verification.objects.get(pk=t['receipt'])
  r.expires_at=timezone.now()-timedelta(seconds=1);r.body['expires']=r.expires_at.isoformat();r.mac=seal(r.body);r.save()
  self.unchanged('verification_invalid',PermissionError)
 def test_integrity_and_pre_checked_while_plan_locked(self):
  from actions.readback import validate_locked_pre
  original=Engine.proposal_digest;counts={'integrity':0,'pre':0}
  def locked():
   c=connections['verification']
   try:
    with c.cursor() as q:
     with self.assertRaises(OperationalError):q.execute('SELECT id FROM actions_plan WHERE id=%s FOR UPDATE NOWAIT',[self.p['id']])
   finally:c.close()
  def checked_digest(steps,snapshots):
   counts['integrity']+=1;locked();return original(steps,snapshots)
  def checked_pre(p,actor):
   counts['pre']+=1;self.assertGreater(counts['integrity'],0);locked();return validate_locked_pre(p,actor)
  before(self.actor.pk,self.p['id'])
  with patch.object(Engine,'proposal_digest',side_effect=checked_digest),patch('actions.readback.validate_locked_pre',side_effect=checked_pre):
   self.assertEqual(self.e.execute(self.p['id'])['state'],'succeeded')
  self.assertEqual(counts['pre'],1)
 def test_scopes_before_target_reads_preserved(self):
  from django.db import connection
  from django.contrib.auth.models import User
  selects=[]
  def trace(execute,sql,params,many,context):
   if sql.lstrip().upper().startswith('SELECT') and 'gestion_joueurs_player' in sql:selects.append(sql)
   return execute(sql,params,many,context)
  from django.test import RequestFactory
  from django.test import override_settings
  from actions.http import WriterBoundary,issue_approval
  from django.utils import timezone
  from datetime import timedelta
  with override_settings(ACTIONS_APPROVAL_KEY='FICTION_ORDER_APPROVAL_KEY_NOT_LIVE_001'):
   request=RequestFactory().post('/actions/v1/execute',data={'id':self.p['id'],'approval':issue_approval(self.p['id'],self.actor.pk,Plan.objects.get(pk=self.p['id']).digest,timezone.now()+timedelta(minutes=2))},content_type='application/json')
   with connection.execute_wrapper(trace):
    with self.assertRaisesRegex(PermissionError,'scope_denied'):WriterBoundary(lambda r:None).authorized_dispatch(request,{'actor':self.actor.pk,'scopes':['execute']},'execute')
  self.assertEqual(selects,[])
