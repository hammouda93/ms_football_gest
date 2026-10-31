import unittest,uuid
from datetime import date,timedelta
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from actions.engine import Engine
from gestion_joueurs.models import Player

class ReadbackTests(unittest.TestCase):
 def http_execute(self,pk):
  from http_helpers import execute
  return execute(self.actor.pk,pk)

 def setUp(self):
  self.actor=User.objects.create(username='FICTION_RB_'+uuid.uuid4().hex,is_superuser=True)
  self.player=Player.objects.create(name='FICTION_PRIVATE',club='CLUB',league='OC',position='MF',date_of_birth=date(2002,1,2),whatsapp_number='+21612345678')
  self.e=Engine(self.actor.pk)
  self.p=self.e.prepare(uuid.uuid4().hex,[{'as':'p','op':'player.profile.amend','values':{'id':self.player.pk,'name':'FICTION_NEW'}}])
  settings.ACTIONS_VERIFICATION_KEY=uuid.uuid4().hex+uuid.uuid4().hex
 def test_http_mixed_profile_workflow_and_redaction(self):
  from actions.readback import before,after
  from gestion_joueurs.models import Video,VideoEditor,Invoice
  from client_portal.models import VideoWorkflow
  editor=User.objects.create(username='FICTION_EDITOR_'+uuid.uuid4().hex)
  ve=VideoEditor.objects.create(user=editor)
  video=Video.objects.create(player=self.player,editor=ve,status='pending',total_payment=300,advance_payment=0,season='2025/2026',deadline=date(2030,1,1))
  Invoice.objects.create(video=video,total_amount=300,amount_paid=0,status='unpaid',created_by=self.actor)
  steps=[{'as':'p','op':'player.profile.amend','values':{'id':self.player.pk,'name':'FICTION_MIXED'}},{'as':'w','op':'video.workflow.transition','values':{'id':video.pk,'stage':'blocked','priority':'urgent','progress':0,'next_action':'FICTION_PRIVATE_NOTE','blocked_reason':'FICTION_PRIVATE_REASON'}}]
  import json
  from pathlib import Path
  from urllib.request import Request,urlopen
  R=Path(__file__).parent
  def call(pk,phase):
   (R/'http-fixture.json').write_text(json.dumps({'actor':self.actor.pk,'scopes':['verify','op:player.profile.amend','op:video.workflow.transition'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat()}))
   req=Request('http://127.0.0.1:'+('55851' if phase=='before' else '55853')+'/actions/v1/verify',data=json.dumps({'id':pk,'phase':phase}).encode(),headers={'Authorization':'Bearer FICTION_READBACK_TOKEN','Content-Type':'application/json'})
   with urlopen(req,timeout=10) as response:return json.load(response)
  before=lambda actor,pk:call(pk,'before')
  after=lambda actor,t:call(t['receipt'],'after')
  p=self.e.prepare(uuid.uuid4().hex,steps);ticket=before(self.actor.pk,p['id'])
  self.assertEqual(self.http_execute(p['id'])['state'],'succeeded')
  verdict=after(self.actor.pk,ticket)
  self.assertEqual(verdict['verdict'],'verified')
  import json
  self.assertNotIn('FICTION_PRIVATE',json.dumps(verdict))
  self.assertNotIn('+216',json.dumps(verdict))
  VideoWorkflow.objects.filter(video=video).update(blocked_reason='CHANGED')
  self.assertEqual(after(self.actor.pk,ticket)['verdict'],'mismatch')
 def test_actor_foreign_expiry_scope_and_tamper(self):
  from actions.readback import before,after
  from actions.models import Verification,Plan
  from django.core.exceptions import ObjectDoesNotExist
  with self.assertRaises(PermissionError):before(self.actor.pk,self.p['id'],['verify'])
  with self.assertRaises(ObjectDoesNotExist):before(self.actor.pk+100000,self.p['id'])
  t=before(self.actor.pk,self.p['id'])
  with self.assertRaises(ObjectDoesNotExist):after(self.actor.pk+100000,t)
  Verification.objects.filter(pk=t['receipt']).update(expires_at=timezone.now()-timedelta(seconds=1))
  with self.assertRaises(PermissionError):after(self.actor.pk,t)
  t=before(self.actor.pk,self.p['id']);r=Verification.objects.get(pk=t['receipt']);r.body['baseline']={};r.save()
  with self.assertRaisesRegex(ValueError,'verification_integrity'):after(self.actor.pk,t)
  Plan.objects.filter(pk=self.p['id']).update(digest='0'*64)
  with self.assertRaisesRegex(ValueError,'verification_integrity'):before(self.actor.pk,self.p['id'])
 def test_readonly_dml_rollback_and_caller_transaction(self):
  from actions.readback import readonly
  from django.db import connections,transaction,DatabaseError
  c=connections['verification']
  with self.assertRaises(DatabaseError):
   with readonly():
    with c.cursor() as q:q.execute("UPDATE gestion_joueurs_player SET club='FORBIDDEN' WHERE id=%s",[self.player.pk])
  self.player.refresh_from_db();self.assertEqual(self.player.club,'CLUB')
  self.assertIsNone(c.connection)
  with transaction.atomic(using='verification'):
   with self.assertRaisesRegex(ValueError,'verification_transaction_owned'):
    with readonly():pass
   self.assertTrue(c.in_atomic_block)
 def test_uncovered_operation_and_field_refused(self):
  from actions.models import Plan
  from actions.readback import before
  for steps in [[{'as':'x','op':'sql','values':{}}],[{'as':'x','op':'video.amend','values':{'id':1,'password':'NO'}}]]:
   p=Plan.objects.create(actor_id=self.actor.pk,key=uuid.uuid4().hex,steps=steps)
   with self.assertRaises(ValueError):before(self.actor.pk,str(p.pk))
 def test_not_committed_cannot_pass(self):
  from actions.readback import before,after
  from actions.models import Plan
  t=before(self.actor.pk,self.p['id'])
  self.assertEqual(after(self.actor.pk,t)['verdict'],'not_committed')
  from django.db import transaction
  try:
   with transaction.atomic():
    self.e.execute(self.p['id'])
    raise RuntimeError('late rollback')
  except RuntimeError:pass
  self.assertEqual(after(self.actor.pk,t)['verdict'],'not_committed')

 def test_contract_matrix(self):
  from actions.readback import before,after
  import json
  from pathlib import Path
  from urllib.request import Request,urlopen
  R=Path(__file__).parent
  def call(pk,phase):
   import time
   time.sleep(.13) # honour lab's one-second quota, never reset buckets
   (R/'http-fixture.json').write_text(json.dumps({'actor':self.actor.pk,'scopes':['verify',*['op:'+op for op in self.e.catalogue()]],'expires':(timezone.now()+timedelta(minutes=5)).isoformat()}))
   req=Request('http://127.0.0.1:'+('55851' if phase=='before' else '55853')+'/actions/v1/verify',data=json.dumps({'id':pk,'phase':phase}).encode(),headers={'Authorization':'Bearer FICTION_READBACK_TOKEN','Content-Type':'application/json'})
   with urlopen(req,timeout=10) as response:return json.load(response)
  before=lambda actor,pk:call(pk,'before')
  after=lambda actor,t:call(t['receipt'],'after')
  from client_portal.models import Organization,OrganizationPlayer
  from prospects.models import Prospect
  from gestion_joueurs.models import Video,VideoEditor,Invoice
  org=Organization.objects.create(name='FICTION_ORG',kind='academy',country='Tunisia')
  prospect=Prospect.objects.create(full_name='FICTION_PROSPECT',whatsapp_number='+21612345678',country='Tunisia',club='CLUB',league='OC',position='midfielder',season='2025/2026',service_type='highlights',match_links='https://example.invalid/match')
  editor=User.objects.create(username='FICTION_MATRIX_'+uuid.uuid4().hex);ve=VideoEditor.objects.create(user=editor)
  video=Video.objects.create(player=self.player,editor=ve,status='pending',total_payment=300,advance_payment=0,season='2025/2026',deadline=date(2030,1,1))
  Invoice.objects.create(video=video,total_amount=300,amount_paid=0,status='unpaid',created_by=self.actor)
  cases=[
   ('player.create',dict(name='FICTION_CREATE_'+uuid.uuid4().hex,club='CLUB',league='OC',position='MF',date_of_birth='2002-01-02')),
   ('organization.link',dict(player=self.player.pk,organization=org.pk,expected_matches=3)),
   ('video.order',dict(player=self.player.pk,editor=ve.pk,client_organization=org.pk,whatsapp_conversation_date='2030-01-01',deadline_from_whatsapp=True,match_package=3,season='2024/2025',advance_payment='0',info='FICTION_INFO')),
   ('player.amend',dict(id=self.player.pk,club='FICTION_CLUB')),
   ('video.amend',dict(id=video.pk,info='FICTION_INFO')),
   ('organization.details.amend',dict(id=org.pk,contact_name='FICTION_CONTACT')),
   ('prospect.details.amend',dict(id=prospect.pk,internal_notes='FICTION_PRIVATE')),
   ('player.profile.create',dict(name='FICTION_PROFILE_'+uuid.uuid4().hex,club='CLUB',league='OC',position='MF',date_of_birth='2002-01-02',whatsapp_number='+21612345678')),
   ('organization.profile.create',dict(name='FICTION_PROFILE_ORG',kind='academy',contact_name='FICTION',country='Tunisia',whatsapp_number='+21612345678')),
   ('organization.profile.amend',dict(id=org.pk,whatsapp_number='+21612345679')),
   ('prospect.profile.amend',dict(id=prospect.pk,club='FICTION_CLUB')),
   ('player.profile.amend',dict(id=self.player.pk,name='FICTION_NEW')),
   ('video.status.transition',dict(id=video.pk,status='in_progress')),
   ('video.workflow.transition',dict(id=video.pk,stage='blocked',priority='urgent',progress=0,next_action='FICTION_NEXT',blocked_reason='FICTION_REASON'))]
  results=[]
  for op,values in cases:
   with self.subTest(operation=op):
    p=self.e.prepare(uuid.uuid4().hex,[{'as':'target','op':op,'values':values}]);t=before(self.actor.pk,p['id'])
    self.assertEqual(self.http_execute(p['id'])['state'],'succeeded')
    outcome=after(self.actor.pk,t)
    if outcome['verdict']!='verified':
     from actions.models import Plan,Verification
     from actions.readback import readonly,graph,expected_graph
     with readonly():
      obj=Plan.objects.using('verification').get(pk=p['id']);rec=Verification.objects.using('verification').get(pk=t['receipt']);g=graph(obj,obj.results);eg=expected_graph(obj,rec.body['baseline'],g)
      print('MISMATCH_KEYS',[(x['model'],[(k,row[k],erow.get(k)) for row,erow in zip(x['rows'],eg[key]['rows']) for k in row if row[k]!=erow.get(k)]) for key,x in g.items() if x!=eg[key]])
    self.assertEqual(outcome['verdict'],'verified',op)
    results.append(op)
  from pathlib import Path
  import json
  (Path(__file__).parent/'matrix.json').write_text(json.dumps(results))

 def test_real_http_distinct_process_and_refusals(self):
  import json,os
  from pathlib import Path
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  R=Path(__file__).parent
  self.assertNotEqual(json.loads((R/'ready-55851.json').read_text())['pid'],os.getpid())
  cfg={'actor':self.actor.pk,'scopes':['verify','op:player.profile.amend'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat()}
  def call(data):
   (R/'http-fixture.json').write_text(json.dumps(cfg))
   req=Request('http://127.0.0.1:55851/actions/v1/verify',data=json.dumps(data).encode(),headers={'Authorization':'Bearer FICTION_READBACK_TOKEN','Content-Type':'application/json'})
   try:
    with urlopen(req,timeout=10) as r:return r.status,json.load(r)
   except HTTPError as r:return r.code,json.load(r)
  code,t=call({'id':self.p['id'],'phase':'before'});self.assertEqual(code,200,t)
  self.assertEqual(self.http_execute(self.p['id'])['state'],'succeeded')
  code,r=call({'id':t['receipt'],'phase':'after'});self.assertEqual((code,r['verdict']),(200,'verified'))
  cfg['scopes']=['verify'];self.assertEqual(call({'id':t['receipt'],'phase':'after'})[0],403)
  cfg['scopes']=['verify','op:player.profile.amend'];cfg['actor']+=10000;self.assertEqual(call({'id':t['receipt'],'phase':'after'})[0],404)
  cfg['actor']=self.actor.pk;cfg['expires']=(timezone.now()-timedelta(seconds=1)).isoformat();self.assertEqual(call({'id':t['receipt'],'phase':'after'})[0],403)
  cfg['expires']=(timezone.now()+timedelta(minutes=5)).isoformat();self.assertEqual(call({'id':t['receipt'],'phase':'after','fields':['password']})[0],400)
  (R/'native-fixture.json').write_text(json.dumps({'plan':self.p['id']}))
  (R/'http-proof.json').write_text(json.dumps({'server_pid':json.loads((R/'ready-55851.json').read_text())['pid'],'execute_pid':os.getpid(),'verdict':r,'negative_statuses':[403,404,403,400]}))

 def test_relation_and_excluded_field_changes_detected(self):
  from actions.readback import before,after
  t=before(self.actor.pk,self.p['id'])
  self.e.execute(self.p['id'])
  Player.objects.filter(pk=self.player.pk).update(email='fiction@example.invalid')
  self.assertEqual(after(self.actor.pk,t)['verdict'],'mismatch')
 def test_effect_count_tamper_and_actor_revocation(self):
  from actions.readback import before,after
  from actions.models import Plan
  t=before(self.actor.pk,self.p['id']);self.e.execute(self.p['id'])
  p=Plan.objects.get(pk=self.p['id']);p.effects['notifications']=[999999];p.save()
  with self.assertRaisesRegex(ValueError,'verification_effect_ids'):after(self.actor.pk,t)
  p.effects['notifications']=[];p.save()
  self.actor.is_active=False;self.actor.save()
  with self.assertRaises(PermissionError):after(self.actor.pk,t)

 def test_native_seed(self):
  import json
  from pathlib import Path
  R=Path(__file__).parent
  (R/'native-fixture.json').write_text(json.dumps({'plan':self.p['id']}))
  (R/'http-fixture.json').write_text(json.dumps({'actor':self.actor.pk,'scopes':['verify','op:player.profile.amend'],'expires':(timezone.now()+timedelta(minutes=10)).isoformat()}))

 def test_secret_columns_never_projected(self):
  from actions.readback import FIELDS,readonly,rows
  self.assertTrue(all(not any(word in f.lower() for word in ('token','password','secret')) for fields in FIELDS.values() for f in fields.split()))
  self.assertNotIn('auth.User',FIELDS)
  with readonly():
   with self.assertRaisesRegex(ValueError,'verification_model_forbidden'):rows('auth.User',pk=self.actor.pk)
 def test_relation_binding_detected_after_execute(self):
  from actions.readback import before,after
  from client_portal.models import Organization
  from gestion_joueurs.models import Video,VideoEditor
  editor=User.objects.create(username=uuid.uuid4().hex);ve=VideoEditor.objects.create(user=editor)
  org=Organization.objects.create(name='FICTION_REL',kind='academy')
  video=Video.objects.create(player=self.player,editor=ve,client_organization=org,status='pending',total_payment=300,advance_payment=0,season='2025/2026',deadline=date(2030,1,1))
  p=self.e.prepare(uuid.uuid4().hex,[{'as':'v','op':'video.amend','values':{'id':video.pk,'info':'FICTION_PRIVATE'}}]);t=before(self.actor.pk,p['id']);self.e.execute(p['id'])
  Video.objects.filter(pk=video.pk).update(client_organization=None)
  self.assertEqual(after(self.actor.pk,t)['verdict'],'mismatch')

 def test_independent_readback_compares_persistence_not_success(self):
  from actions.readback import before,after
  ticket=before(self.actor.pk,self.p['id'])
  self.assertEqual(self.e.execute(self.p['id'])['state'],'succeeded')
  self.assertEqual(after(self.actor.pk,ticket)['verdict'],'verified')
  Player.objects.filter(pk=self.player.pk).update(name='CHANGED_AFTER_EXECUTE')
  self.assertEqual(after(self.actor.pk,ticket)['verdict'],'mismatch')
