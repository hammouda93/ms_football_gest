"""Access-policy qualification; fixtures are not human approval."""
import os,json,uuid,hashlib,unittest,copy
from datetime import timedelta
from unittest.mock import patch
from django.test import override_settings,RequestFactory
from django.utils import timezone
from actions import mount,pilot
from actions.registry import catalogue

class ConfigurationTests(unittest.TestCase):
 def credential(self):
  return {'actor':37,'scopes':['catalogue','prepare','status','execute',*['op:'+n for n in catalogue()]],'expires':(timezone.now()+timedelta(hours=1)).isoformat(),'revoked':False}
 def test_all_fourteen_explicit_scopes_parse(self):
  c=self.credential();self.assertEqual(len(catalogue()),14)
  with patch.dict(os.environ,{'MSF_ACTIONS_PILOT_CONFIG':json.dumps({'enabled':True,'credentials':{'a'*64:c}})},clear=True):
   self.assertEqual(mount._configuration(),{'enabled':True,'credentials':{'a'*64:c}})

 def test_general_binding_accepts_configured_actor_and_exact_operations(self):
  binding={'plan_id':str(uuid.uuid4()),'digest':'b'*64,'actor':37,'operations':['player.profile.amend','video.workflow.transition']}
  with patch.dict(os.environ,{'MSF_ACTIONS_EXECUTE_ENABLED':'true','MSF_ACTIONS_APPROVAL_KEY':'FICTION-'+uuid.uuid4().hex,'MSF_ACTIONS_EXECUTE_BINDING':json.dumps(binding)},clear=True):
   enabled,key,actual=mount.execute_configuration()
   self.assertTrue(enabled);self.assertEqual(actual,binding)

class BindingTests(unittest.TestCase):
 def test_each_contract_and_composition_passes_exact_digest_guard(self):
  from actions.models import Plan
  from actions.engine import Engine
  for names in ([n] for n in catalogue()):
   steps=[{'as':'s'+str(i),'op':n,'values':{}} for i,n in enumerate(names)]
   digest=Engine.proposal_digest(steps,{})
   p=Plan(id=uuid.uuid4(),actor_id=37,steps=steps,snapshots={},digest=digest)
   b={'plan_id':str(p.pk),'actor':37,'digest':digest,'operations':names}
   pilot._check_plan(p,b)
  names=['player.create','organization.link','video.order']
  steps=[{'as':'s'+str(i),'op':n,'values':{}} for i,n in enumerate(names)]
  digest=Engine.proposal_digest(steps,{})
  p=Plan(id=uuid.uuid4(),actor_id=37,steps=steps,snapshots={},digest=digest)
  pilot._check_plan(p,{'plan_id':str(p.pk),'actor':37,'digest':digest,'operations':names})

 def test_malformed_binding_is_permission_denied(self):
  from actions.models import Plan
  p=Plan(id=uuid.uuid4(),actor_id=37,steps=[],snapshots={},digest='b'*64)
  with self.assertRaises(PermissionError):pilot._check_plan(p,{})

class RuntimeTests(unittest.TestCase):
 def test_invalid_permit_closes_before_connection_auth_quota(self):
  req=RequestFactory().post('/actions/v1/execute',data='{}',content_type='application/json')
  with override_settings(ACTIONS_ENABLED=True,ACTIONS_EXECUTE_ENABLED=True,ACTIONS_EXECUTE_BINDING={},ACTIONS_APPROVAL_KEY='FICTION-'+uuid.uuid4().hex):
   with patch('django.db.connection.get_autocommit',side_effect=AssertionError('SQL boundary reached')):
    r=pilot.PrepareOnlyBoundary(lambda r:None)(req)
    self.assertEqual(r.status_code,403);self.assertEqual(json.loads(r.content),{'error':'execute_disabled_pilot'})

class NegativeTests(ConfigurationTests):
 def test_config_negative_matrix(self):
  base=self.credential()
  for change in ({'scopes':['catalogue','prepare','status','op:crud']},{'scopes':['catalogue','prepare','status','op:https://x']},{'actor':True},{'expires':(timezone.now()+timedelta(days=2)).isoformat()},{'expires':'not-date'},{'revoked':'false'}):
   c=dict(base,**change)
   with self.subTest(change=list(change)):
    with self.assertRaises(ValueError):mount._configuration(json.dumps({'enabled':True,'credentials':{'a'*64:c}}))
  for change in ({'revoked':True},{'expires':(timezone.now()-timedelta(seconds=1)).isoformat()}):
   self.assertFalse(mount._configuration(json.dumps({'enabled':True,'credentials':{'a'*64:dict(base,**change)}}))['enabled'])
 def test_runtime_config_negative_matrix_before_sql_and_site_available(self):
  from django.http import HttpResponse
  boundary=pilot.PrepareOnlyBoundary(lambda r:HttpResponse('site-ok'))
  base=self.credential()
  for c in (dict(base,revoked=True),dict(base,expires='malformed'),dict(base,expires=(timezone.now()-timedelta(seconds=1)).isoformat()),dict(base,scopes=base['scopes']+['op:crud'])):
   with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={'a'*64:c}):
    with patch('django.db.connection.get_autocommit',side_effect=AssertionError('SQL reached')):
     self.assertEqual(boundary(RequestFactory().get('/actions/v1/catalogue')).status_code,403)
     self.assertEqual(boundary(RequestFactory().get('/ordinary')).content,b'site-ok')
 def test_binding_tampering_and_deferred_without_sql(self):
  from actions.models import Plan
  from actions.engine import Engine
  steps=[{'as':'p','op':'player.amend','values':{'id':7,'club':'FICTION'}}]
  p=Plan(id=uuid.uuid4(),actor_id=37,steps=steps,snapshots={},digest=Engine.proposal_digest(steps,{}))
  b={'plan_id':str(p.pk),'actor':37,'digest':p.digest,'operations':['player.amend']}
  for change in ({'actor':1},{'digest':'a'*64},{'operations':['video.amend']},{'operations':['crud']},{'plan_id':str(uuid.uuid4())}):
   with self.assertRaises(PermissionError):pilot._check_plan(p,dict(b,**change))
  p.snapshots={'tampered':True}
  with self.assertRaises(PermissionError):pilot._check_plan(p,b)
  p=Plan(id=uuid.uuid4())
  with patch('django.db.connection.cursor',side_effect=AssertionError('deferred SQL')):
   with self.assertRaises(PermissionError):pilot._check_plan(p,b)
 def test_contextvar_isolation_and_reset(self):
  import contextvars
  token=pilot._active_binding.set({'sentinel':True})
  try:self.assertIsNone(contextvars.Context().run(pilot._active_binding.get))
  finally:pilot._active_binding.reset(token)
  self.assertIsNone(pilot._active_binding.get())
 def test_reader_digest_reuse_and_registry_drift_close(self):
  c=self.credential();req=RequestFactory().get('/actions/v1/catalogue')
  with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={'a'*64:c},DATA_ACCESS_CREDENTIALS=[{'token_hash':'a'*64}]):
   with patch('django.db.connection.get_autocommit',side_effect=AssertionError('SQL reached')):
    self.assertEqual(pilot.PrepareOnlyBoundary(lambda r:None)(req).status_code,403)
  with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS={'a'*64:c}):
   with patch('actions.registry.catalogue',return_value={'crud':{}}):self.assertEqual(pilot.PrepareOnlyBoundary(lambda r:None)(req).status_code,403)

if __name__=='__main__':unittest.main(verbosity=2)
