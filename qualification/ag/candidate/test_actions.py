import copy,uuid,unittest
from datetime import date,timedelta
from decimal import Decimal
from django.db import connection,transaction
from django.contrib.auth.models import User
from gestion_joueurs.models import Player,Video,VideoEditor,Invoice,VideoStatusHistory,Payment,AutomationRun
from client_portal.models import Organization,OrganizationPlayer,PortalProfile

class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.atomic=transaction.atomic();self.atomic.__enter__()
        self.actor=User.objects.create(username='FICTION_ADMIN_'+uuid.uuid4().hex,is_active=True,is_superuser=True)
        self.editor=VideoEditor.objects.create(user=self.actor)
        self.org=Organization.objects.create(name='FICTION_AGENCY',kind='agent')
        self.name='FICTION_PLAYER_'+uuid.uuid4().hex
        self.key=uuid.uuid4().hex
        self.baseline={m:m.objects.count() for m in (Invoice,VideoStatusHistory,OrganizationPlayer,AutomationRun,PortalProfile,Payment)}
    def tearDown(self):
        transaction.set_rollback(True);self.atomic.__exit__(None,None,None)
    def plan(self):
        return [
          {'as':'p','op':'player.create','values':{'name':self.name,'club':'FICTION_CLUB','league':'OC','position':'MF','date_of_birth':'2002-01-02'}},
          {'as':'link','op':'organization.link','values':{'player':{'ref':'p'},'organization':self.org.pk,'expected_matches':5}},
          {'as':'order','op':'video.order','values':{'player':{'ref':'p'},'editor':self.editor.pk,'client_organization':self.org.pk,'whatsapp_conversation_date':date.today().isoformat(),'deadline_from_whatsapp':True,'match_package':5,'season':'2025/2026','advance_payment':'0.00','info':'FICTION montage instructions'}}]
    def engine(self):
        from actions.engine import Engine
        return Engine(self.actor.pk)
    def test_catalogue_and_unknown_field_refused_before_write(self):
        e=self.engine()
        self.assertEqual(set(e.catalogue()),{'player.create','organization.link','video.order','player.amend','video.amend'})
        bad=self.plan();bad[0]['values']['client_vip']=True
        with self.assertRaisesRegex(ValueError,'field_forbidden'):e.prepare(self.key,bad)
        self.assertFalse(Player.objects.filter(name=self.name).exists())
        from actions.models import Audit
        self.assertTrue(Audit.objects.filter(actor_id=self.actor.pk,event='refused',code='field_forbidden').exists())
    def test_permissions_rechecked_and_external_effects_closed(self):
        e=self.engine();p=e.prepare(self.key,self.plan())
        User.objects.filter(pk=self.actor.pk).update(is_superuser=False)
        with self.assertRaisesRegex(PermissionError,'permission_denied'):e.execute(p['id'])
        with self.assertRaisesRegex(PermissionError,'permission_denied'):e.prepare('another',self.plan())
        with self.assertRaisesRegex(PermissionError,'permission_denied'):e.status(p['id'])
        User.objects.filter(pk=self.actor.pk).update(is_superuser=True)
        for operation in ['email.send','whatsapp.send','job.start','account.create','performance.activate','sql','python']:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError,'operation_forbidden'):
                    e.prepare(operation,[{'as':'x','op':operation,'values':{}}])
        self.assertFalse(Player.objects.filter(name=self.name).exists())
    def test_retry_same_key_no_second_write_and_payload_mismatch(self):
        e=self.engine();p=e.prepare(self.key,self.plan());first=e.execute(p['id'])
        # Simulate response lost after commit: caller discards response, new engine reads DB.
        fresh=self.engine()
        self.assertEqual(fresh.execute(p['id']),first)
        self.assertEqual(fresh.prepare(self.key,self.plan())['id'],p['id'])
        self.assertEqual(Video.objects.filter(player__name=self.name).count(),1)
        changed=self.plan();changed[0]['values']['club']='FICTION_DIFFERENT'
        with self.assertRaisesRegex(ValueError,'idempotency_mismatch'):fresh.prepare(self.key,changed)
    def test_duplicate_identity_is_refused_and_whole_plan_rolled_back(self):
        e=self.engine();e.execute(e.prepare(self.key,self.plan())['id'])
        other=e.prepare('duplicate',self.plan())
        result=e.execute(other['id'])
        self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'duplicate_player')
        self.assertEqual(Player.objects.filter(name=self.name).count(),1)
        self.assertEqual(result['results'],{})
        from actions.models import Audit
        self.assertTrue(Audit.objects.filter(plan_id=other['id'],event='failed',code='duplicate_player').exists())
    def test_encadrée_modification_and_stale_snapshot_conflict(self):
        e=self.engine();created=e.execute(e.prepare(self.key,self.plan())['id'])
        player=created['results']['p'];video=created['results']['order']
        changes=[{'as':'p','op':'player.amend','values':{'id':player,'club':'FICTION_NEW_CLUB'}},{'as':'v','op':'video.amend','values':{'id':video,'info':'FICTION additional instructions'}}]
        p=e.prepare('amend',changes)
        self.assertEqual(Player.objects.get(pk=player).club,'FICTION_CLUB')
        result=e.execute(p['id']);self.assertEqual(result['state'],'succeeded')
        self.assertEqual(Player.objects.get(pk=player).club,'FICTION_NEW_CLUB')
        self.assertEqual(Video.objects.get(pk=video).info,'FICTION additional instructions')
        stale=e.prepare('stale',changes)
        Player.objects.filter(pk=player).update(club='FICTION_HUMAN_EDIT')
        conflict=e.execute(stale['id'])
        self.assertEqual(conflict['state'],'failed');self.assertEqual(conflict['error'],'conflict')
        self.assertEqual(Player.objects.get(pk=player).club,'FICTION_HUMAN_EDIT')
    def test_late_invalid_operation_rolls_back_prior_player_link_and_video(self):
        e=self.engine();steps=self.plan()
        steps.append({'as':'bad','op':'video.order','values':dict(steps[-1]['values'],season='INVALID')})
        p=e.prepare(self.key,steps);result=e.execute(p['id'])
        self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'invalid_video')
        self.assertFalse(Player.objects.filter(name=self.name).exists())
        self.assertEqual(Invoice.objects.count(),self.baseline[Invoice]);self.assertEqual(VideoStatusHistory.objects.count(),self.baseline[VideoStatusHistory])
        self.assertEqual(OrganizationPlayer.objects.count(),self.baseline[OrganizationPlayer])
        self.assertEqual(e.execute(p['id']),result)
    def test_inconsistent_link_nonzero_payment_and_automation_are_refused(self):
        e=self.engine()
        cases=[('advance_payment','10.00','payment_not_supported'),('deadline_from_whatsapp',False,'automatic_deadline_required')]
        for field,value,code in cases:
            steps=self.plan();steps[-1]['values'][field]=value
            p=e.prepare(uuid.uuid4().hex,steps);r=e.execute(p['id'])
            self.assertEqual(r['error'],code)
            self.assertFalse(Player.objects.filter(name=self.name).exists())
        steps=self.plan();steps[1]['values']['expected_matches']=3
        r=e.execute(e.prepare('mismatch',steps)['id'])
        self.assertEqual(r['error'],'organization_link_mismatch')
        self.assertEqual(Invoice.objects.count(),self.baseline[Invoice])
    def test_postgres_cross_connection_busy_refusal(self):
        import psycopg2
        e=self.engine();p=e.prepare(self.key,self.plan())
        other=psycopg2.connect(host='127.0.0.1',port=55440,user='msf_action01_fixture_owner',dbname='msf_action03_fiction')
        try:
            with other.cursor() as c:c.execute('SELECT pg_advisory_xact_lock(41001,1)')
            with self.assertRaisesRegex(ValueError,'busy'):e.execute(p['id'])
            self.assertFalse(Player.objects.filter(name=self.name).exists())
            self.assertEqual(e.status(p['id'])['state'],'prepared')
        finally:other.rollback();other.close()
        self.assertEqual(e.execute(p['id'])['state'],'succeeded')
    def test_server_validation_of_links_references_and_model_errors(self):
        e=self.engine()
        bad=self.plan();bad[1]['values']['player']={'ref':'order'}
        with self.assertRaisesRegex(ValueError,'invalid_reference'):e.prepare('forward',bad)
        bad=self.plan();bad[1]['values']['expected_matches']=99
        r=e.execute(e.prepare('invalid_matches',bad)['id'])
        self.assertEqual(r['error'],'invalid_link')
        bad=self.plan();bad[0]['values']['position']='ZZ'
        self.assertEqual(e.execute(e.prepare('invalid_position',bad)['id'])['error'],'invalid_player')
        bad=self.plan();bad[1]['values']['organization']=99999999
        self.assertEqual(e.execute(e.prepare('missing_org',bad)['id'])['error'],'target_missing')
        self.assertFalse(Player.objects.filter(name=self.name).exists())
    def test_failed_prepare_does_not_leave_executable_orphan(self):
        from actions.models import Plan
        with self.assertRaisesRegex(ValueError,'target_missing'):
            self.engine().prepare(self.key,[{'as':'p','op':'player.amend','values':{'id':99999999,'club':'FICTION'}}])
        self.assertFalse(Plan.objects.filter(actor_id=self.actor.pk,key=self.key).exists())
    def test_strict_types_unknown_step_keys_and_foreign_plan_access(self):
        e=self.engine()
        for field,value in [('editor',True),('match_package','5'),('deadline_from_whatsapp','true'),('season',5),('client_organization','2')]:
            bad=self.plan();bad[-1]['values'][field]=value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'invalid_type'):e.prepare(uuid.uuid4().hex,bad)
        bad=self.plan();bad[0]['url']='https://invalid.test'
        with self.assertRaisesRegex(ValueError,'invalid_step'):e.prepare('badkey',bad)
        p=e.prepare(self.key,self.plan())
        stranger=User.objects.create(username='FICTION_OTHER_ADMIN_'+uuid.uuid4().hex,is_superuser=True,is_active=True)
        from actions.engine import Engine
        from actions.models import Plan
        with self.assertRaises(Plan.DoesNotExist):Engine(stranger.pk).status(p['id'])
        with self.assertRaises(Plan.DoesNotExist):Engine(stranger.pk).execute(p['id'])
    def test_existing_order_duplicate_and_side_effect_footprint(self):
        from django.apps import apps
        from django.core import mail
        monitored=['client_portal.PortalProfile','sportsbase_data.SportsBaseSubscription','sportsbase_data.SportsBaseSyncJob','gestion_joueurs.AutomationRun','gestion_joueurs.AutomationEvent','gestion_joueurs.AutomationWorker','client_portal.CommunicationLog','client_portal.PaymentRequest']
        models=[apps.get_model(name) for name in monitored]
        before={m._meta.label:m.objects.count() for m in models}
        mail_before=len(getattr(mail,'outbox',[]))
        e=self.engine();r=e.execute(e.prepare(self.key,self.plan())['id'])
        steps=self.plan()[2:];steps[0]['values']['player']=r['results']['p']
        duplicate=e.execute(e.prepare('duplicate_order',steps)['id'])
        self.assertEqual(duplicate['error'],'duplicate_order')
        self.assertEqual(before,{m._meta.label:m.objects.count() for m in models})
        self.assertEqual(mail_before,len(getattr(mail,'outbox',[])))
    def test_prepared_payload_tampering_refused(self):
        from actions.models import Plan
        e=self.engine();p=e.prepare(self.key,self.plan())
        tampered=self.plan();tampered[0]['values']['club']='FICTION_TAMPERED'
        Plan.objects.filter(pk=p['id']).update(steps=tampered)
        with self.assertRaisesRegex(ValueError,'plan_integrity'):e.execute(p['id'])
        self.assertFalse(Player.objects.filter(name=self.name).exists())
    def test_create_composed_player_link_order_invoice(self):
        e=self.engine();prepared=e.prepare(self.key,self.plan())
        self.assertFalse(Player.objects.filter(name=self.name).exists())
        result=e.execute(prepared['id'])
        self.assertEqual(result['state'],'succeeded')
        p=Player.objects.get(pk=result['results']['p']);v=Video.objects.get(pk=result['results']['order'])
        self.assertEqual(p.name,self.name);self.assertEqual(p.position,'MF')
        self.assertTrue(OrganizationPlayer.objects.filter(player=p,organization=self.org,expected_matches=5).exists())
        self.assertEqual(v.player_id,p.pk);self.assertEqual(v.editor_id,self.editor.pk)
        self.assertEqual(v.deadline,date.today()+timedelta(days=5))
        self.assertEqual(v.total_payment,Decimal('350.00'))
        self.assertEqual(v.invoices.total_amount,Decimal('350.00'));self.assertEqual(v.invoices.amount_paid,0)
        self.assertEqual(v.status,'pending');self.assertEqual(v.invoices.created_by_id,self.actor.pk)
        self.assertEqual(VideoStatusHistory.objects.filter(video=v).count(),1)
        self.assertEqual(AutomationRun.objects.count(),self.baseline[AutomationRun]);self.assertEqual(PortalProfile.objects.count(),self.baseline[PortalProfile]);self.assertEqual(Payment.objects.count(),self.baseline[Payment])
        self.assertEqual(e.status(prepared['id'])['results'],result['results'])
