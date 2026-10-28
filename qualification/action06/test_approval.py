import unittest,copy,uuid
from datetime import timedelta
from django.utils import timezone
from test_http import HTTPTests
from test_actions import ActionsTests
from actions.models import Plan
from actions.http import issue_approval

class ApprovalTests(unittest.TestCase):
 setUp=HTTPTests.setUp
 tearDown=ActionsTests.tearDown
 plan=ActionsTests.plan
 engine=ActionsTests.engine
 post=HTTPTests.post
 def test_preview_and_preconditions_returned_for_approval(self):
  p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
  self.assertEqual(p['preview']['operations'],self.plan())
  order=p['preview']['orders'][0]
  self.assertEqual(order['price'],'350.00')
  self.assertEqual(order['advance_payment'],'0.00')
  self.assertEqual(order['effects'],['video','invoice','history','possible_internal_notification'])
  self.assertTrue(p['preconditions'])
 def test_changed_preconditions_cannot_reuse_approval(self):
  p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
  approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
  Plan.objects.filter(pk=p['id']).update(snapshots={'forged':'new'})
  r=self.post('execute',{'id':p['id'],'approval':approval})
  self.assertEqual(r.status_code,403,r.content)
  self.assertEqual(Plan.objects.get(pk=p['id']).state,'prepared')
 def test_organization_dependency_change_conflicts(self):
  p=self.post('prepare',{'key':self.key,'steps':self.plan()}).json()
  approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
  type(self.org).objects.filter(pk=self.org.pk).update(name='FICTION_CHANGED')
  r=self.post('execute',{'id':p['id'],'approval':approval})
  self.assertEqual(r.status_code,200,r.content)
  self.assertEqual(r.json()['error'],'conflict')
