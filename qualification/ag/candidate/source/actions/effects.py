"""Capture newly inserted internal effects in the current execution context."""
from contextvars import ContextVar
from contextlib import contextmanager
from django.db.models.signals import post_save
from gestion_joueurs.models import VideoStatusHistory,Notification,Invoice
from client_portal.models import VideoActivity
_active=ContextVar('action_effects',default=None)
_MODELS={VideoStatusHistory:'history',Notification:'notifications',Invoice:'invoices'}
def capture(sender,instance,created,**kwargs):
    value=_active.get()
    if value is not None and created and sender is VideoActivity and 'activities' in value:value['activities'].append(instance.pk)
    if value is not None and created and sender in _MODELS:value[_MODELS[sender]].append(instance.pk)
post_save.connect(capture,weak=False,dispatch_uid='action02_effect_capture')
@contextmanager
def effects_context(workflow=False):
    value={k:[] for k in _MODELS.values()}
    if workflow:value['activities']=[]
    token=_active.set(value)
    try:yield value
    finally:_active.reset(token)
