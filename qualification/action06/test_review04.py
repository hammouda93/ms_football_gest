"""Targeted review regressions on real PostgreSQL and Django HTTP boundary."""
import hashlib,json,unittest,uuid
from datetime import timedelta
from django.apps import apps
from django.core import mail
from django.utils import timezone
from test_http import HTTPTests
from test_actions import ActionsTests
from actions.models import Plan
from actions.http import issue_approval
from client_portal.models import OrganizationPlayer

class Review04Tests(unittest.TestCase):
    setUp=HTTPTests.setUp
    tearDown=ActionsTests.tearDown
    plan=ActionsTests.plan
    engine=ActionsTests.engine
    post=HTTPTests.post

    def footprint(self):
        # Exact rows, not just counts: detects amendment/notification/history leaks.
        rows={m._meta.label:list(m.objects.order_by('pk').values()) for m in apps.get_models()
              if m._meta.app_label in ('gestion_joueurs','client_portal','sportsbase_data','prospects') and m._meta.managed}
        return hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest(),len(getattr(mail,'outbox',[]))

    def membership_conflict(self,operation):
        created=self.engine().execute(self.engine().prepare(self.key,self.plan())['id'])
        self.assertEqual(created['state'],'succeeded')
        player=created['results']['p']
        source=self.plan()[1 if operation=='organization.link' else 2]
        source['values']['player']={'ref':'existing'}
        if operation=='video.order':source['values']['season']='2026/2027'
        steps=[{'as':'existing','op':'player.amend','values':{'id':player,'club':'FICTION_MUST_NOT_CHANGE'}},source]
        prepared=self.post('prepare',{'key':uuid.uuid4().hex,'steps':steps}).json()
        # Literal-ID oracle: concrete preconditions must be exactly the same.
        import copy
        literal=copy.deepcopy(steps);literal[-1]['values']['player']=player
        control=self.engine().snapshots(literal)
        actual=Plan.objects.get(pk=prepared['id']).snapshots
        key='membership:'+str(player)+':'+str(self.org.pk)
        self.assertIn(key,actual)
        self.assertEqual({k:v for k,v in actual.items() if k!='__preview__'},
                         {k:v for k,v in control.items() if k!='__preview__'})
        approval=issue_approval(prepared['id'],self.actor.pk,prepared['digest'],timezone.now()+timedelta(minutes=2))
        # Update finishes before execute (not an in-flight concurrency claim).
        OrganizationPlayer.objects.filter(pk=created['results']['link']).update(expected_matches=3)
        before=self.footprint()
        response=self.post('execute',{'id':prepared['id'],'approval':approval})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['state'],'failed')
        self.assertEqual(response.json()['error'],'conflict')
        self.assertEqual(response.json()['results'],{})
        self.assertEqual(response.json()['effects'],{})
        self.assertEqual(self.footprint(),before)
        print('A04_CONFLICT',json.dumps({'operation':operation,'error':response.json()['error'],'before':before,'after':self.footprint(),'results':response.json()['results'],'effects':response.json()['effects'],'literal_preconditions_equal':True}))

    def test_alias_amend_membership_link_conflicts_without_mutation(self):
        self.membership_conflict('organization.link')

    def test_alias_amend_membership_order_conflicts_without_mutation(self):
        self.membership_conflict('video.order')

    def reject_payment(self,value):
        steps=self.plan();steps[-1]['values']['advance_payment']=value
        before=self.footprint();plans=Plan.objects.count()
        response=self.post('prepare',{'key':self.key,'steps':steps})
        self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(response.json(),{'error':'invalid_request'})
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(Plan.objects.count(),plans)
        self.assertEqual(self.footprint(),before)
        with self.assertRaisesRegex(ValueError,'payment_not_supported'):
            self.engine().prepare(self.key,steps)
        self.assertEqual(Plan.objects.count(),plans)
        self.assertEqual(self.footprint(),before)
        print('A04_PAYMENT',json.dumps({'value':value,'http_status':response.status_code,'body':response.json(),'plans_before':plans,'plans_after':Plan.objects.count(),'before':before,'after':self.footprint()}))

    def test_snan_payment_http400_without_plan_or_effects(self):
        self.reject_payment('sNaN')

    def test_nan_payment_http400_without_plan_or_effects(self):
        self.reject_payment('NaN')

    def test_infinity_payment_http400_without_plan_or_effects(self):
        self.reject_payment('Infinity')

    def test_negative_infinity_payment_http400_without_plan_or_effects(self):
        self.reject_payment('-Infinity')

    def test_date_overflow_http400_without_orphan_plan_or_effects(self):
        steps=self.plan();steps[-1]['values']['whatsapp_conversation_date']='9999-12-31'
        before=self.footprint();plans=Plan.objects.count()
        response=self.post('prepare',{'key':self.key,'steps':steps})
        self.assertEqual(response.status_code,400,response.content)
        self.assertEqual(response.json(),{'error':'invalid_request'})
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(Plan.objects.count(),plans)
        self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=self.key).exists())
        self.assertEqual(self.footprint(),before)
        with self.assertRaisesRegex(ValueError,'invalid_deadline'):
            self.engine().prepare(self.key,steps)
        self.assertEqual(Plan.objects.count(),plans)
        self.assertEqual(self.footprint(),before)
        print('A04_DATE',json.dumps({'value':'9999-12-31','http_status':response.status_code,'body':response.json(),'plans_before':plans,'plans_after':Plan.objects.count(),'before':before,'after':self.footprint()}))
