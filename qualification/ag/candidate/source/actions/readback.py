"""Exact-plan verification, never an analytical query interface.
Private baseline kept in technical receipt, not returned to the model.
"""
import hashlib,hmac,json,uuid
from contextlib import contextmanager
from datetime import timedelta
from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections,transaction
from django.utils import timezone
from .engine import Engine
from .registry import catalogue
from .models import Plan,Verification,Audit

# Closed server policy. These are business columns, not '*', and never auth.User,
# portal credentials, automation claim tokens or arbitrary caller field names.
FIELDS={
 'gestion_joueurs.Player':'id name club email date_of_birth age whatsapp_number league position client_fidel client_vip player_creation_date sportsbase_url transfermarkt_url',
 'gestion_joueurs.Video':'id player_id editor_id status advance_payment total_payment deadline client_organization_id whatsapp_conversation_date deadline_from_whatsapp match_package matches_processed delivery_date video_link client_portal_visible seasons_to_process processing_mode delivery_mode automation_started automation_completed delivery_automation_started delivery_automation_completed info season club intro_photo intro_automation_enabled intro_presentation_style intro_automation_started intro_automation_completed league salary_paid_status video_creation_date',
 'client_portal.Organization':'id name kind contact_name email whatsapp_number country google_sheet_id google_sheet_tab google_sheet_last_synced_at google_sheet_last_error is_active created_by_id created_at updated_at',
 'prospects.Prospect':'id full_name transfermarkt_url date_of_birth whatsapp_number email country club league position season service_type match_links desired_deadline message source status internal_notes player_id created_at updated_at',
 'client_portal.OrganizationPlayer':'id organization_id player_id label expected_matches is_active ended_at added_by_id created_at',
 'client_portal.VideoWorkflow':'id video_id stage priority progress next_action blocked_reason updated_by_id created_at updated_at',
 'gestion_joueurs.VideoStatusHistory':'id video_id editor_id status changed_at comment created_by_id',
 'client_portal.VideoActivity':'id video_id kind visibility message metadata created_by_id created_at',
 'gestion_joueurs.Notification':'id user_id message is_read created_at video_id notification_type sent_at sent_by_id player_id',
 'gestion_joueurs.Invoice':'id video_id invoice_date total_amount amount_paid status created_by_id payment_method',
}
EFFECTS={'history':'gestion_joueurs.VideoStatusHistory','activities':'client_portal.VideoActivity','notifications':'gestion_joueurs.Notification','invoices':'gestion_joueurs.Invoice'}
ALIAS='verification'
def scalar(v):return json.loads(json.dumps(v,cls=DjangoJSONEncoder,sort_keys=True,allow_nan=False))
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def seal(v):
 key=getattr(settings,'ACTIONS_VERIFICATION_KEY','')
 if type(key) is not str or len(key)<32:raise PermissionError('verification_unconfigured')
 return hmac.new(key.encode(),json.dumps(v,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
@contextmanager
def readonly():
 c=connections[ALIAS]
 if c.in_atomic_block or not c.get_autocommit():raise ValueError('verification_transaction_owned')
 try:
  with transaction.atomic(using=ALIAS):
   with c.cursor() as q:
    q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    q.execute("SELECT set_config('statement_timeout','2000ms',true),set_config('lock_timeout','200ms',true)")
   yield
   transaction.set_rollback(True,using=ALIAS)
 finally:c.close()
def rows(label,_alias=ALIAS,**filters):
 if label not in FIELDS:raise ValueError('verification_model_forbidden')
 qs=apps.get_model(label).objects.using(_alias).filter(**filters).order_by('pk')
 if _alias=='default':qs=qs.select_for_update()
 result=scalar(list(qs.values(*FIELDS[label].split())[:257]))
 if len(result)>256 or len(json.dumps(result))>240000:raise ValueError('verification_bound')
 return result
def plan(actor,pk,scopes=None):
 p=Plan.objects.using(ALIAS).get(pk=pk,actor_id=actor)
 if type(p.steps) is not list or not 1<=len(p.steps)<=12:raise ValueError('verification_bound')
 for step in p.steps:
  if type(step) is not dict or set(step)!= {'as','op','values'} or type(step['values']) is not dict:raise ValueError('verification_contract_forbidden')
 User=apps.get_model('auth','User')
 user=User.objects.using(ALIAS).filter(pk=actor,is_active=True).values('is_superuser').first()
 if not user:raise PermissionError('verification_actor')
 if not user['is_superuser']:
  if any(s.get('op') not in ('video.status.transition','video.workflow.transition') for s in p.steps):raise PermissionError('verification_actor')
  editor=apps.get_model('gestion_joueurs.VideoEditor').objects.using(ALIAS).filter(user_id=actor).values_list('pk',flat=True).first()
  for s in p.steps:
   if not apps.get_model('gestion_joueurs.Video').objects.using(ALIAS).filter(pk=s['values'].get('id'),editor_id=editor).exists():raise PermissionError('verification_actor')
 if not 1<=len(p.steps)<=12:raise ValueError('verification_bound')
 rules=catalogue()
 for s in p.steps:
  if type(s.get('op')) is not str or s['op'] not in rules:raise ValueError('verification_contract_forbidden')
  if scopes is not None and 'op:'+s['op'] not in scopes:raise PermissionError('scope_denied')
  rule=rules[s['op']]
  if type(s['values']) is not dict or set(s['values'])-set(rule['fields']):raise ValueError('verification_field_forbidden')
 if Engine.proposal_digest(p.steps,p.snapshots)!=p.digest:raise ValueError('verification_integrity')
 return p
def graph(p,results,_alias=ALIAS):
 out={};rules=catalogue()
 def add(label,**kw):
  key=label+':'+json.dumps(kw,sort_keys=True)
  out[key]={'model':label,'filter':kw,'rows':rows(label,_alias=_alias,**kw)}
 for s in p.steps:
  v=s['values'];pk=results.get(s['as'],v.get('id'))
  if pk is not None:
   if type(pk) is not int or pk<=0:raise ValueError('verification_ids')
   add(rules[s['op']]['model'],pk=pk)
  # Relations are exact values/aliases from the reviewed contract, never paths.
  for name,label in [('player','gestion_joueurs.Player'),('organization','client_portal.Organization'),('client_organization','client_portal.Organization')]:
   x=v.get(name)
   if isinstance(x,dict):x=results.get(x['ref'])
   if type(x) is int:add(label,pk=x)
  if s['op']=='organization.link':
   x=v['player'];x=results.get(x['ref']) if isinstance(x,dict) else x
   if type(x) is int:add('client_portal.OrganizationPlayer',player_id=x,organization_id=v['organization'])
  if rules[s['op']]['model']=='gestion_joueurs.Video' and pk:
   video=rows('gestion_joueurs.Video',_alias=_alias,pk=pk)
   if video:
    add('gestion_joueurs.Player',pk=video[0]['player_id'])
    if video[0]['client_organization_id']:add('client_portal.Organization',pk=video[0]['client_organization_id'])
   for label in ['client_portal.VideoWorkflow',*EFFECTS.values()]:add(label,video_id=pk)
 if len(out)>96 or len(json.dumps(out))>480000:raise ValueError('verification_bound')
 return out

def validate_locked_pre(p, actor):
 """Called only with the execute plan lock; latest PRE must be intact."""
 from datetime import datetime
 rec=Verification.objects.select_for_update().filter(plan=p,actor_id=actor).order_by('-created_at','-pk').first()
 if rec is None:raise PermissionError('verification_required')
 try:
  b=rec.body
  if (set(b)!={'plan','actor','digest','baseline','expires'} or b['actor']!=actor
      or b['plan']!=str(p.pk) or b['digest']!=p.digest
      or Engine.proposal_digest(p.steps,p.snapshots)!=p.digest
      or rec.expires_at!=datetime.fromisoformat(b['expires'])
      or not hmac.compare_digest(rec.mac,seal(b))):raise ValueError()
  if p.state=='prepared' and rec.expires_at<=timezone.now():raise ValueError()
 except (ValueError,TypeError,KeyError):raise PermissionError('verification_invalid') from None
 return rec

def before(actor,pk,scopes=None):
 # PRE receipt and audit commit with the exact locked plan, never after releasing it.
 with transaction.atomic():
  p=Plan.objects.select_for_update().get(pk=pk,actor_id=actor)
  if p.state!='prepared':raise ValueError('verification_requires_prepared')
  with readonly():plan(actor,pk,scopes)
  e=Engine(actor);e.authorize();e.validate(p.steps)
  if e.snapshots(p.steps,lock=True)!=p.snapshots:raise ValueError('conflict')
  with readonly():baseline=graph(p,{})
  body={'plan':str(p.pk),'actor':actor,'digest':p.digest,'baseline':baseline,'expires':(timezone.now()+timedelta(minutes=10)).isoformat()}
  receipt=Verification.objects.create(plan_id=p.pk,actor_id=actor,body=body,mac=seal(body),expires_at=body['expires'])
  Audit.objects.create(plan=p,actor_id=actor,event='verification_pre',code=str(receipt.pk))
 return {'receipt':str(receipt.pk),'plan':str(p.pk),'digest':p.digest,'expires':body['expires']}
def after(actor,ticket,scopes=None):
 try:result=_after(actor,ticket,scopes)
 except (ValueError,PermissionError,apps.get_model('actions','Verification').DoesNotExist):
  Audit.objects.create(actor_id=actor,event='verification_refused',code='post_invalid')
  raise
 Audit.objects.create(plan_id=result['plan'],actor_id=actor,event='verification_post',code=result['verdict'])
 return result

def _after(actor,ticket,scopes=None):
 rid=ticket['receipt'] if isinstance(ticket,dict) else ticket
 with readonly():
  rec=Verification.objects.using(ALIAS).get(pk=rid,actor_id=actor)
  from datetime import datetime
  if rec.expires_at<=timezone.now() or rec.expires_at!=datetime.fromisoformat(rec.body['expires']):raise PermissionError('verification_expired')
  b=rec.body
  if not hmac.compare_digest(rec.mac,seal(b)) or b['actor']!=actor or str(rec.plan_id)!=b['plan']:raise ValueError('verification_integrity')
  p=plan(actor,b['plan'],scopes)
  if p.digest!=b['digest']:raise ValueError('verification_integrity')
  if p.state!='succeeded':return {'verdict':'not_committed','plan':str(p.pk),'digest':p.digest}
  if not Audit.objects.using(ALIAS).filter(plan=p,actor_id=actor,event='verification_bound',code=str(rec.pk)).exists():raise ValueError('verification_not_bound')
  if set(p.results)!={s['as'] for s in p.steps} or any(type(x) is not int or x<=0 for x in p.results.values()):raise ValueError('verification_ids')
  for s in p.steps:
   if 'id' in s['values'] and p.results[s['as']]!=s['values']['id']:raise ValueError('verification_ids')
  current=graph(p,p.results)
  expected=expected_graph(p,b['baseline'],current)
  ok=current==expected
  return {'verdict':'verified' if ok else 'mismatch','plan':str(p.pk),'digest':p.digest,'observedHash':digest(current),'expectedHash':digest(expected),'ids':p.results}

def expected_graph(p,baseline,current):
 """Apply approved old/new to private PRE rows; generated columns are excluded.
 The POST is real persisted data; only explicit generated fields are copied.
 """
 from copy import deepcopy
 expected=deepcopy(baseline);rules=catalogue();preview=p.snapshots['__preview__']
 changes={x['as']:x for x in preview.get('changes',[])}
 transitions={x['as']:x for x in preview.get('transitions',[])}
 orders={x['as']:x for x in preview.get('orders',[])}
 # Include newly created rows and exact relation sets in the post graph.
 for key,g in current.items():
  if key not in expected:expected[key]=dict(g,rows=[])
 def resolve(v):return p.results[v['ref']] if isinstance(v,dict) else v
 def patch(label,pk,new,create=False,generated=()):
  found=False
  for key,g in expected.items():
   if g['model']!=label:continue
   actual=current[key]['rows']
   target=[r for r in actual if r['id']==pk]
   candidates=[r for r in g['rows'] if r['id']==pk]
   if not candidates and create and target:
    # Start with model defaults, not actual client-controlled values.
    obj=apps.get_model(label)()
    row=scalar({n:(str(getattr(obj,n)) if hasattr(getattr(obj,n),'field') else getattr(obj,n)) for n in FIELDS[label].split()})
    row.update({n:target[0][n] for n in generated});row['id']=pk
    g['rows'].append(row);g['rows'].sort(key=lambda r:r['id']);candidates=[row]
   for row in candidates:
    row.update(new);found=True
  if not found:raise ValueError('verification_target_missing')
 for s in p.steps:
  op=s['op'];v={k:resolve(x) for k,x in s['values'].items()};pk=p.results[s['as']];label=rules[op]['model']
  if s['as'] in changes:
   x=changes[s['as']]
   patch(label,pk,x['new'],x['old'] is None,x.get('generated',[]))
  elif s['as'] in transitions:
   x=transitions[s['as']]
   patch(label,pk,{'status':x['newStatus']})
   if x['newWorkflow'] is not None:
    group=next(g for g in current.values() if g['model']=='client_portal.VideoWorkflow' and g['filter']=={'video_id':pk})
    if len(group['rows'])!=1:raise ValueError('verification_workflow_missing')
    wf=group['rows'][0]
    new=dict(x['newWorkflow'],video_id=pk)
    if op=='video.workflow.transition' or x['newWorkflow']!=x['oldWorkflow']:new['updated_by_id']=p.actor_id
    patch('client_portal.VideoWorkflow',wf['id'],new,True,('id','created_at','updated_at'))
    # auto_now is intentional only when a real workflow save occurred.
    if op=='video.workflow.transition' or x['newWorkflow']!=x['oldWorkflow']:
     for key,g in expected.items():
      if g['model']=='client_portal.VideoWorkflow':
       for row in g['rows']:
        if row['id']==wf['id']:row['updated_at']=wf['updated_at']
  elif op in ('player.amend','video.amend'):patch(label,pk,{k:x for k,x in v.items() if k!='id'})
  elif op=='player.create':
   birth=__import__('datetime').date.fromisoformat(v['date_of_birth']);today=__import__('datetime').date.today()
   patch(label,pk,dict(v,age=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))),True,('id','player_creation_date'))
  elif op=='organization.link':patch(label,pk,dict(player_id=v['player'],organization_id=v['organization'],expected_matches=v['expected_matches'],is_active=True,ended_at=None,added_by_id=p.actor_id),True,('id','created_at'))
  elif op=='video.order':
   o=orders[s['as']];player=rows('gestion_joueurs.Player',pk=v['player'])[0]
   new={k:x for k,x in v.items() if k not in ('player','editor','client_organization')}
   new.update(client_portal_visible=False,player_id=v['player'],editor_id=v['editor'],client_organization_id=v['client_organization'],deadline=o['deadline'],total_payment=o['price'],advance_payment='0.00',club=player['club'],league=player['league'])
   patch(label,pk,new,True,('id','video_creation_date'))
  else:raise ValueError('verification_contract_forbidden')
 # Effects: exact newly inserted IDs AND their approved values, no global diff.
 for kind,label in EFFECTS.items():
  ids=p.effects.get(kind,[])
  if not isinstance(ids,list) or len(ids)>256 or any(type(i) is not int or i<=0 for i in ids) or len(set(ids))!=len(ids):raise ValueError('verification_ids')
  actual=[];prior=[]
  for g in current.values():
   if g['model']==label:actual+=g['rows']
  for g in baseline.values():
   if g['model']==label:prior+=g['rows']
  prior_ids={r['id'] for r in prior};new={r['id']:r for r in actual if r['id'] not in prior_ids}
  if set(new)!=set(ids):raise ValueError('verification_effect_ids')
  predictions=[]
  for s in p.steps:
   pk=p.results[s['as']]
   if s['as'] in transitions:
    x=transitions[s['as']];field={'history':'history','activities':'activities','notifications':'notifications'}.get(kind)
    if field:predictions += [dict(r,**({'video_id':pk} if 'video_id' not in r else {})) for r in x[field]]
   elif s['op']=='video.order':
    if kind=='invoices':predictions.append({'video_id':pk,'total_amount':orders[s['as']]['price'],'amount_paid':'0.00','status':'unpaid','created_by_id':p.actor_id,'payment_method':None})
    # The signal's create history is deterministic; notification only if editor.
    elif kind=='history':predictions.append({'video_id':pk,'editor_id':s['values']['editor'],'status':'pending','comment':'Video created.','created_by_id':p.actor_id})
    elif kind=='notifications':
     editor_id=apps.get_model('gestion_joueurs.VideoEditor').objects.using(ALIAS).values_list('user_id',flat=True).get(pk=s['values']['editor'])
     if editor_id and editor_id!=p.actor_id:
      video=apps.get_model('gestion_joueurs.Video').objects.using(ALIAS).get(pk=pk)
      # __str__ uses player; attach an alias-bound instance to avoid default SQL.
      video.player=apps.get_model('gestion_joueurs.Player').objects.using(ALIAS).get(pk=video.player_id)
      predictions.append({'user_id':editor_id,'message':f'Vous avez été assigné à une nouvelle vidéo : {video}','notification_type':'inter_user','video_id':pk,'sent_by_id':p.actor_id,'player_id':video.player_id,'is_read':False})
  if len(new)!=len(predictions):raise ValueError('verification_effect_count')
  projected=[{k:r[k] for k in prediction} for r,prediction in zip(sorted(new.values(),key=lambda r:r['id']),predictions)]
  if len(projected)!=len(predictions) or projected!=predictions:raise ValueError('verification_effect_content')
  for key,g in expected.items():
   if g['model']==label:
    for r in current[key]['rows']:
     if r['id'] in new:g['rows'].append(r)
    g['rows'].sort(key=lambda r:r['id'])
 return expected
