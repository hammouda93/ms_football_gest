"""UNIFIED01 real signed HTTP; full effects and readback evidence."""
import unittest,uuid,json,hashlib,threading,os
from pathlib import Path
from datetime import timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from wsgiref.simple_server import make_server,WSGIRequestHandler
from django.test import override_settings
from django.utils import timezone
from django.core.wsgi import get_wsgi_application
from actions.http import issue_approval
from actions.models import Plan
from test_workflow import WorkflowTests
from test_wf01 import business_rows,assert_effects
from gestion_joueurs.models import Player
R=Path(__file__).resolve().parent
class Quiet(WSGIRequestHandler):
 def log_message(self,*a):pass
class Unified01Tests(unittest.TestCase):
 def exercise(self,values,reverse=False,unrelated=False,alias='profile'):
  t=WorkflowTests();t.setUp()
  if unrelated:
   other=Player.objects.create(name='FICTION_OTHER',club='CLUB',league='OC',position='MF');pk=other.pk
  else:pk=t.player.pk
  steps=[{'as':alias,'op':'player.profile.amend','values':dict(id=pk,**values)}]+t.steps('completed')
  if reverse:steps.reverse()
  token=uuid.uuid4().hex
  cred={'actor':t.admin.pk,'scopes':['prepare','execute','status',*['op:'+s['op'] for s in steps]],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
  with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
   server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet);thread=threading.Thread(target=server.serve_forever);thread.start()
   try:
    def call(route,payload):
     req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
     with urlopen(req,timeout=20) as response:self.assertEqual(response.status,200);return json.load(response)
    before={t.video.pk:business_rows(t.video.pk)};old=Player.objects.values().get(pk=pk)
    p=call('prepare',{'key':uuid.uuid4().hex,'steps':steps});plan=Plan.objects.get(pk=p['id'])
    self.assertEqual(before[t.video.pk],business_rows(t.video.pk));self.assertEqual(old,Player.objects.values().get(pk=pk))
    approval=issue_approval(p['id'],t.admin.pk,p['digest'],timezone.now()+timedelta(minutes=2))
    result=call('execute',{'id':p['id'],'approval':approval});self.assertEqual(result['state'],'succeeded',result)
    self.assertEqual(call('status',{'id':p['id']}),result);self.assertEqual(call('execute',{'id':p['id'],'approval':approval}),result)
    record={'kind':self._testMethodName,'pid':os.getpid(),'video':t.video.pk,'player_id':pk,'player':Player.objects.values().get(pk=pk),'plan':p['id'],'preview':p['preview'],'result':result,'before':before[t.video.pk],'readback':business_rows(t.video.pk),'signed_fixture':True,'http':[200,200,200,200]}
    with (R/'unified01-records.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record,default=str)+'\n')
    assert_effects(self,plan,result,before)
    expected=dict(old,**plan.snapshots['__preview__']['changes'][0]['new'])
    self.assertEqual(Player.objects.values().get(pk=pk),expected)
    msg=p['preview']['transitions'][0]['notifications'][0]['message']
    if not reverse and not unrelated:
     for field in ('name','whatsapp_number'):
      if field in values:self.assertIn(values[field],msg)
    return record
   finally:server.shutdown();server.server_close();thread.join(5);self.assertFalse(thread.is_alive())
 def test_name_before_completed_signed_http_exact_effects(self):self.exercise({'name':'FICTION_NEW_NAME'})
 def test_whatsapp_before_completed_signed_http_exact_effects(self):self.exercise({'whatsapp_number':'+21612345678'})
 def test_name_and_whatsapp_before_completed(self):self.exercise({'name':'FICTION_BOTH','whatsapp_number':'+21687654321'})
 def test_reverse_order_consumes_original_player(self):
  r=self.exercise({'name':'FICTION_AFTER','whatsapp_number':'+21612345678'},reverse=True)
  self.assertNotIn('FICTION_AFTER',r['preview']['transitions'][0]['notifications'][0]['message'])
 def test_unrelated_player_does_not_change_effects(self):
  r=self.exercise({'name':'FICTION_UNRELATED','whatsapp_number':'+21612345678'},unrelated=True)
  self.assertNotIn('FICTION_UNRELATED',r['preview']['transitions'][0]['notifications'][0]['message'])
 def test_nonconsumed_fields_are_effect_invariant(self):self.exercise({'club':'FICTION_CLUB','position':'GK'})
 def test_step_alias_does_not_change_dependency_projection(self):
  # Aliases name results, not player identity; literal target IDs bind effects.
  self.exercise({'name':'FICTION_ALIAS','whatsapp_number':'+21612345678'},alias='renamed_producer')
 def test_refused_historical_signed_plan_and_http_prepare_leave_no_business_write(self):
  import importlib.util
  from actions.engine import Engine
  t=WorkflowTests();t.setUp()
  steps=[{'as':'a','op':'player.amend','values':{'id':t.player.pk,'club':'FICTION_A'}},{'as':'b','op':'player.profile.amend','values':{'id':t.player.pk,'name':'FICTION_B'}}]+t.steps('completed')
  spec=importlib.util.spec_from_file_location('actions.unified_prior',R.parent/'unified/source/actions/engine.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
  historical=prior.Engine(t.admin.pk).prepare(uuid.uuid4().hex,steps);p=Plan.objects.get(pk=historical['id'])
  before=business_rows(t.video.pk);old=Player.objects.values().get(pk=t.player.pk);count=Plan.objects.count();frozen=(p.digest,p.snapshots,p.state,p.effects)
  token=uuid.uuid4().hex;cred={'actor':t.admin.pk,'scopes':['prepare','execute','status',*['op:'+s['op'] for s in steps]],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}
  with override_settings(ACTIONS_ENABLED=True,ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex,ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():cred},MIDDLEWARE=['actions.http.OperationalWriterBoundary'],ALLOWED_HOSTS=['127.0.0.1']):
   approval=issue_approval(p.pk,t.admin.pk,p.digest,timezone.now()+timedelta(minutes=2))
   server=make_server('127.0.0.1',55573,get_wsgi_application(),handler_class=Quiet);thread=threading.Thread(target=server.serve_forever);thread.start()
   try:
    for route,payload in [('prepare',{'key':uuid.uuid4().hex,'steps':steps}),('execute',{'id':str(p.pk),'approval':approval})]:
     req=Request('http://127.0.0.1:55573/actions/v1/'+route,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
     with self.assertRaises(HTTPError) as caught:urlopen(req,timeout=20)
     error=caught.exception;self.assertEqual(error.code,400);self.assertEqual(json.load(error),{'error':'plan_dependency_not_simulable'})
    p.refresh_from_db();self.assertEqual((p.digest,p.snapshots,p.state,p.effects),frozen)
    self.assertEqual(Plan.objects.count(),count);self.assertEqual(business_rows(t.video.pk),before);self.assertEqual(Player.objects.values().get(pk=t.player.pk),old)
    record={'kind':'refused_signed_historical','pid':os.getpid(),'video':t.video.pk,'player_id':t.player.pk,'player':old,'plan':str(p.pk),'readback':before,'frozen':json.loads(json.dumps(frozen,default=str))}
    with (R/'refusal-records.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record,default=str)+'\n')
   finally:server.shutdown();server.server_close();thread.join(5);self.assertFalse(thread.is_alive())
 def test_repeated_player_producers_refused_without_plan_or_business_writes(self):
  from actions.engine import Engine
  for reverse in (False,True):
   t=WorkflowTests();t.setUp()
   producers=[{'as':'a','op':'player.amend','values':{'id':t.player.pk,'club':'FICTION_A'}},{'as':'b','op':'player.profile.amend','values':{'id':t.player.pk,'name':'FICTION_B'}}]
   if reverse:producers.reverse()
   steps=producers+t.steps('completed');before=business_rows(t.video.pk);old=Player.objects.values().get(pk=t.player.pk);count=Plan.objects.count()
   with self.assertRaisesRegex(ValueError,'plan_dependency_not_simulable'):t.engine.prepare(uuid.uuid4().hex,steps)
   self.assertEqual(Plan.objects.count(),count);self.assertEqual(business_rows(t.video.pk),before);self.assertEqual(Player.objects.values().get(pk=t.player.pk),old)
