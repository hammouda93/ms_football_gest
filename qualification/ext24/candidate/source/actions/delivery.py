"""Internal final-state registration through the real production view; no send/upload."""
from urllib.parse import urlsplit,unquote
import re

def public_path(path):
 """Inspect one strict UTF-8 decode only; reject nested escapes/route ambiguities.
 The original URL is never rewritten. Percent after decoding is forbidden,
 so double/multiple encodings cannot acquire meaning at a downstream layer.
 """
 if re.search(r'%(?![0-9A-Fa-f]{2})',path):raise ValueError('public_final_link_required')
 try:decoded=unquote(path,encoding='utf-8',errors='strict')
 except UnicodeError:raise ValueError('public_final_link_required') from None
 if '%' in decoded:raise ValueError('public_final_link_required')
 for value in (path,decoded):
  if any(ord(c)<33 or ord(c)==127 for c in value) or any(c in value for c in '\\?#;') or '//' in value or any(s in ('.','..','access') for s in value.split('/')):
   raise ValueError('public_final_link_required')
from django.utils import timezone
from .workflow import ProductionTransition,external_effects_closed
from client_portal.forms import ProductionVideoStatusForm
from client_portal.services import invoice_snapshot

class InternalDelivery(ProductionTransition):
 def __init__(self):super().__init__('status')
 def contract(self):
  return {'model':'gestion_joueurs.Video','fields':['id','video_link'],'required':['id','video_link'],'schema':{'id':{'type':'integer'},'video_link':{'type':'string','format':'uri'}},'family':'internal_delivery/v1','sourceForm':'client_portal.forms.ProductionVideoStatusForm','permission':'active_superuser','effects':['status_history','delivery_date_if_missing','workflow_sync','stage_activity'],'excludedEffects':['send','upload','publication','portal_visibility_change','access_generation','jobs'],'composition':'single_step_only'}
 def cleaned(self,values,actor_id,lock=False):
  actor=self.actor(actor_id)
  if not actor.is_superuser:raise PermissionError('permission_denied')
  obj=self.target(values['id'],actor_id,lock);self.dependencies(obj,lock)
  if obj.status=='delivered':raise ValueError('already_delivered')
  # Access tokens, signed URLs and embedded credentials never enter a signed preview.
  if any(ord(c)<33 or ord(c)==127 for c in values['video_link']):raise ValueError('public_final_link_required')
  u=urlsplit(values['video_link'])
  if u.scheme!='https' or not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment:raise ValueError('public_final_link_required')
  public_path(u.path)
  form=ProductionVideoStatusForm({'status':'delivered','video_link':values['video_link']},user=actor,video=obj)
  if not form.is_valid() or not form.cleaned_data['video_link']:raise ValueError('invalid_delivery_form')
  obj._delivery_clean=form.cleaned_data
  return obj,form.cleaned_data
 def preview(self,step,actor_id,projected_players=None):
  x=super().preview(step,actor_id,projected_players)
  obj,clean=self.cleaned(step['values'],actor_id);payment=invoice_snapshot(obj)
  x['history'][0]['comment']='Video Delivered.'
  x['videoChanges']={'video_link':clean['video_link'],'delivery_date':(obj.delivery_date or timezone.localdate()).isoformat()}
  x['portal']={'visible_before':obj.client_portal_visible,'visible_after':obj.client_portal_visible,'balance':str(payment.balance),'final_available_after':payment.balance<=0,'access_rights_unchanged':True,'sent':False,'uploaded':False}
  return x
 def apply(self,values,actor_id):
  from client_portal.views import production_video_status_update
  from .view_adapter import request_for
  obj,clean=self.cleaned(values,actor_id,True)
  with external_effects_closed():response=production_video_status_update(request_for(actor_id,dict(clean,notification_action='none')),obj.pk)
  if response.status_code!=302:raise ValueError('delivery_view_failed')
  obj.refresh_from_db()
  if obj.status!='delivered' or obj.video_link!=clean['video_link']:raise ValueError('delivery_not_persisted')
  return obj

DELIVERY={'video.delivery.internal':InternalDelivery()}
