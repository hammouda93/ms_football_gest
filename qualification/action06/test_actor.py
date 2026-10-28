import unittest,uuid
from types import SimpleNamespace
from django.http import HttpResponse
from django.template.response import SimpleTemplateResponse
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from gestion_joueurs.middleware import CurrentUserMiddleware
from gestion_joueurs.utils import get_current_user,set_current_user,actor_context
from test_actions import ActionsTests

class ActorTests(unittest.TestCase):
    setUp=ActionsTests.setUp
    plan=ActionsTests.plan
    engine=ActionsTests.engine
    def tearDown(self):
        set_current_user(None)
        ActionsTests.tearDown(self)
    def test_normal_exception_render_anonymous_and_sequential_cleanup(self):
        from django.template import engines
        for actor in [self.actor,AnonymousUser(),self.actor]:
            for mode in ['normal','exception','render']:
                req=RequestFactory().get('/');req.user=actor
                def view(request):
                    self.assertEqual(get_current_user(),self.actor if actor.is_authenticated else None)
                    if mode=='exception':raise RuntimeError('FICTION')
                    if mode=='render':return SimpleTemplateResponse(engines['django'].from_string('fiction'))
                    return HttpResponse('fiction')
                try:
                    result=CurrentUserMiddleware(view)(req)
                    if mode=='render':result.render()
                except RuntimeError:pass
                self.assertIsNone(get_current_user(),'actor leaked after '+mode)
    def test_real_editor_change_preserves_notification_recipient(self):
        from gestion_joueurs.models import Video,VideoEditor,Notification
        from django.contrib.auth.models import User
        e=self.engine();r=e.execute(e.prepare(self.key,self.plan())['id'])
        v=Video.objects.get(pk=r['results']['order'])
        user=User.objects.create(username='FICTION_REASSIGN_'+uuid.uuid4().hex)
        editor=VideoEditor.objects.create(user=user)
        with actor_context(self.actor):
            v.editor=editor;v.save(update_fields=['editor'])
        notice=Notification.objects.get(video=v,user=user)
        self.assertEqual(notice.sent_by_id,self.actor.pk)
        self.assertIsNone(get_current_user())
    def test_legacy_previous_editor_cannot_create_false_notification(self):
        from gestion_joueurs.views import thread_local
        from gestion_joueurs.models import Video,VideoEditor,Notification
        from django.contrib.auth.models import User
        other=User.objects.create(username='FICTION_OLD_EDITOR_'+uuid.uuid4().hex)
        editor=VideoEditor.objects.create(user=other)
        steps=self.plan();steps[-1]['values']['editor']=editor.pk
        r=self.engine().execute(self.engine().prepare(self.key,steps)['id'])
        v=Video.objects.get(pk=r['results']['order'])
        before=Notification.objects.filter(video=v).count()
        thread_local.previous_editor=self.editor
        v.info='FICTION info only';v.save(update_fields=['info'])
        self.assertEqual(Notification.objects.filter(video=v).count(),before)
        del thread_local.previous_editor
    def test_fixture_rollback_cannot_leave_stale_actor_or_editor(self):
        from django.db import transaction
        from django.contrib.auth.models import User
        from gestion_joueurs.models import Video,VideoStatusHistory
        with transaction.atomic():
            deleted=User.objects.create(username='FICTION_ROLLBACK_'+uuid.uuid4().hex)
            request=RequestFactory().get('/');request.user=deleted
            CurrentUserMiddleware(lambda r:HttpResponse('fiction'))(request)
            transaction.set_rollback(True)
        self.assertIsNone(get_current_user())
        e=self.engine();r=e.execute(e.prepare(self.key,self.plan())['id'])
        v=Video.objects.get(pk=r['results']['order'])
        v.status='delivered';v.save()
        self.assertIsNone(VideoStatusHistory.objects.filter(video=v).latest('changed_at').created_by_id)
    def test_background_delivered_save_preserves_history_notification_and_date(self):
        from gestion_joueurs.models import Video,VideoStatusHistory,Notification,VideoEditor
        from django.contrib.auth.models import User
        from django.utils import timezone
        e=self.engine();r=e.execute(e.prepare(self.key,self.plan())['id'])
        v=Video.objects.get(pk=r['results']['order'])
        set_current_user(None)
        v.status='delivered';v.save()
        v.refresh_from_db()
        self.assertEqual(v.delivery_date,timezone.localdate())
        self.assertIsNone(VideoStatusHistory.objects.filter(video=v).latest('changed_at').created_by_id)
