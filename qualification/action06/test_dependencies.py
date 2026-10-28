import unittest,uuid
from test_http import HTTPTests
from test_actions import ActionsTests
from client_portal.models import OrganizationPlayer
from actions.models import Plan
from actions.http import issue_approval
from django.utils import timezone
from datetime import timedelta

class DependencyTests(unittest.TestCase):
 setUp=HTTPTests.setUp
 tearDown=ActionsTests.tearDown
 plan=ActionsTests.plan
 engine=ActionsTests.engine
 post=HTTPTests.post
 def test_existing_membership_change_conflicts_before_order(self):
  created=self.engine().execute(self.engine().prepare(self.key,self.plan())['id'])
  steps=self.plan()[2:]
  steps[0]['values'].update(player=created['results']['p'],season='2026/2027')
  prepared=self.post('prepare',{'key':uuid.uuid4().hex,'steps':steps}).json()
  approval=issue_approval(prepared['id'],self.actor.pk,prepared['digest'],timezone.now()+timedelta(minutes=2))
  OrganizationPlayer.objects.filter(pk=created['results']['link']).update(expected_matches=3)
  response=self.post('execute',{'id':prepared['id'],'approval':approval})
  self.assertEqual(response.status_code,200,response.content)
  self.assertEqual(response.json()['error'],'conflict')
  self.assertEqual(response.json()['results'],{})
 def test_malformed_operations_and_missing_amend_info_are_http400_without_plan(self):
  before=Plan.objects.count()
  for operation in [[],{},True,1,None]:
   response=self.post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'x','op':operation,'values':{}}]})
   self.assertEqual(response.status_code,400,response.content)
   self.assertEqual(response.json(),{'error':'invalid_request'})
  response=self.post('prepare',{'key':uuid.uuid4().hex,'steps':[{'as':'v','op':'video.amend','values':{'id':1}}]})
  self.assertEqual(response.status_code,400,response.content)
  self.assertEqual(Plan.objects.count(),before)
 def test_preview_tampering_invalidates_signed_approval(self):
  prepared=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
  approval=issue_approval(prepared['id'],self.actor.pk,prepared['digest'],timezone.now()+timedelta(minutes=2))
  p=Plan.objects.get(pk=prepared['id'])
  p.snapshots['__preview__']['orders'][0]['price']='1.00'
  p.save(update_fields=['snapshots'])
  response=self.post('execute',{'id':p.pk.__str__(),'approval':approval})
  self.assertEqual(response.status_code,403,response.content)
  self.assertEqual(Plan.objects.get(pk=p.pk).state,'prepared')
