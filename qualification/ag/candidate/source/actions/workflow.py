"""Reviewed production transitions; no generic view, arbitrary field or external action."""
import copy,hashlib,json,sys
from contextvars import ContextVar
from contextlib import contextmanager
from django.contrib.auth.models import User
from django.db import transaction
from gestion_joueurs.models import Video,VideoEditor,VideoStatusHistory,Invoice
from client_portal.models import VideoWorkflow
from client_portal.forms import ProductionVideoStatusForm,VideoWorkflowForm
from client_portal.services import production_queryset_for,update_workflow,sync_workflow_to_official_status,allowed_workflow_stages,derived_stage,_automatic_stage,STAGE_PROGRESS,STAGE_NEXT_ACTION

_external_closed=ContextVar('workflow_external_closed',default=False)
def _audit(event,args):
    if _external_closed.get() and event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','os.startfile','os.posix_spawn','smtplib.connect'}:
        raise PermissionError('workflow_external_effect_forbidden')
sys.addaudithook(_audit)
@contextmanager
def external_effects_closed():
    token=_external_closed.set(True)
    try:yield
    finally:_external_closed.reset(token)

FIELDS=('stage','priority','progress','next_action','blocked_reason')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

class ProductionTransition:
    model=Video
    def __init__(self,kind):self.kind=kind
    def contract(self):
        form=ProductionVideoStatusForm() if self.kind=='status' else VideoWorkflowForm()
        names=('status',) if self.kind=='status' else FIELDS
        schema={}
        for n in names:
            f=form.fields[n];r={'requiredByForm':f.required,'type':'integer' if n=='progress' else 'string'}
            if hasattr(f,'choices'):r['enum']=[v for v,label in f.choices]
            if getattr(f,'max_length',None):r['maxLength']=f.max_length
            if n=='progress':r.update(minimum=0,maximum=100)
            schema[n]=r
        return {'model':Video._meta.label,'fields':['id',*names],'required':['id',*names], 'family':'production_transition/v1','schema':schema,'sourceForm':form.__class__.__module__+'.'+form.__class__.__name__,'permission':'active superuser or assigned VideoEditor; actual form restricts transitions','closed':['delivered','external','publication','delivery','access','finance','jobs'],'effects':['status_history','workflow','stage_activity','internal_notifications'],'selection':'target-bound choices in preview; catalogue enums are descriptive'}
    def actor(self,actor_id):
        actor=User.objects.get(pk=actor_id,is_active=True)
        if not actor.is_superuser and not VideoEditor.objects.filter(user=actor).exists():raise PermissionError('permission_denied')
        return actor
    def target(self,pk,actor_id,lock=False):
        actor=self.actor(actor_id)
        # Reuse the real policy without its unbounded prefetch graph.
        qs=production_queryset_for(actor).select_related(None).prefetch_related(None)
        if lock:qs=qs.select_for_update()
        try:return qs.get(pk=pk)
        except Video.DoesNotExist:raise PermissionError('object_permission_denied') from None
    def dependencies(self,obj,lock=False):
        out={}
        for label,qs in [('video',Video.objects.filter(pk=obj.pk)),('workflow',VideoWorkflow.objects.filter(video=obj)),('invoice',Invoice.objects.filter(video=obj)),('runs',obj.automation_runs.filter(is_active=True)),('history',VideoStatusHistory.objects.filter(video=obj).order_by('-changed_at','-pk')[:2]),('admins',User.objects.filter(is_superuser=True).order_by('pk'))]:
            if lock:qs=qs.select_for_update()
            rows=list(qs.values()[:257])
            if len(rows)>256:raise ValueError('workflow_dependency_limit')
            out[label]=rows
        # The real signal orders only by changed_at. Never invent a PK winner.
        if len(out['history'])>1 and out['history'][0]['changed_at']==out['history'][1]['changed_at']:
            raise ValueError('workflow_history_ambiguous')
        # Keep the historical snapshot shape for unambiguous prepared plans.
        out['history']=out['history'][:1]
        if not out['history'] or out['history'][0]['status']!=obj.status:raise ValueError('workflow_history_inconsistent')
        # Bound the service's run reader to this exact observation.
        obj.automation_progress_runs=list(obj.automation_runs.filter(pk__in=[r['id'] for r in out['runs']]).order_by('pk'))
        return out
    def cleaned(self,values,actor_id,lock=False):
        obj=self.target(values['id'],actor_id,lock);actor=self.actor(actor_id)
        self.dependencies(obj,lock)
        if values.get('status')=='delivered' or values.get('stage')=='delivered':raise ValueError('delivery_closed')
        if self.kind=='status':form=ProductionVideoStatusForm(values,user=actor,video=obj)
        else:
            wf=VideoWorkflow.objects.filter(video=obj).first()
            form=VideoWorkflowForm(values,video=obj,instance=copy.copy(wf) if wf else VideoWorkflow(video_id=obj.pk))
        if not form.is_valid():raise ValueError('invalid_transition_form')
        return obj,form.cleaned_data
    def preview(self,step,actor_id,projected_players=None):
        obj,cleaned=self.cleaned(step['values'],actor_id);deps=self.dependencies(obj)
        if projected_players and obj.player_id in projected_players:
            # Substitute the complete validated producer instance, not message
            # string replacements: __str__ and contact fields share this state.
            obj.player=projected_players[obj.player_id]
        old=deps['workflow'][0] if deps['workflow'] else None
        new={k:old[k] for k in FIELDS} if old else None
        activities=[];history=[];notifications=[]
        actor=self.actor(actor_id)
        if self.kind=='workflow':
            previous=derived_stage(obj);new={k:cleaned[k] for k in FIELDS}
            if previous!=new['stage']:
                activities.append({'kind':'stage','visibility':'client','message':f'Étape passée de « {dict(VideoWorkflow.Stage.choices)[previous]} » à « {dict(VideoWorkflow.Stage.choices)[new["stage"]]} ».','metadata':{'from':previous,'to':new['stage']},'created_by_id':actor_id})
        elif cleaned['status']!=obj.status:
            history=[{'status':cleaned['status'],'editor_id':obj.editor_id,'created_by_id':actor_id,'comment':'Status changed.'}]
            after=copy.copy(obj);after.status=cleaned['status']
            if old and old['stage'] not in allowed_workflow_stages(after):
                stage=_automatic_stage(after);new.update(stage=stage,progress=STAGE_PROGRESS.get(stage,old['progress']),next_action=STAGE_NEXT_ACTION.get(stage,''),blocked_reason=old['blocked_reason'] if stage=='blocked' else '')
                activities.append({'kind':'stage','visibility':'internal','message':f'Étape synchronisée avec l’état officiel : « {dict(VideoWorkflow.Stage.choices)[old["stage"]]} » → « {dict(VideoWorkflow.Stage.choices)[stage]} ».','metadata':{'from':old['stage'],'to':stage,'reason':'official_status_sync'},'created_by_id':actor_id})
            message=None
            if after.status=='completed':
                if not deps['invoice']:raise ValueError('invoice_required_for_completed')
                if deps['invoice'][0]['status']!='paid':message=f'la {obj} est finie, contacter le joueur via {obj.player.whatsapp_number} pour finaliser le payement livrer la vidéo'
            if after.status=='completed_collab' and not actor.is_superuser:
                message=f"La '{obj}' a été finie par {obj.editor.user.username} et en attente de finition par l'un des admins."
            if message:
                notifications=[{'user_id':u['id'],'message':message,'notification_type':'inter_user','video_id':obj.pk,'player_id':obj.player_id,'sent_by_id':actor_id,'is_read':False} for u in deps['admins']]
        return {'as':step['as'],'op':step['op'],'id':obj.pk,'oldStatus':obj.status,'newStatus':cleaned.get('status',obj.status),'oldWorkflow':{k:old[k] for k in FIELDS} if old else None,'newWorkflow':new,'history':history,'activities':activities,'notifications':notifications,'outsideActiveProduction':cleaned.get('status',obj.status)=='problematic','externalEffects':[],'contract':self.contract()}
    def snapshot(self,values,actor_id,lock=False):
        obj=self.target(values['id'],actor_id,lock)
        deps=self.dependencies(obj,lock)
        # Text and attribution dependencies used by notification messages.
        deps['player']=obj.player.__dict__.copy();deps['player'].pop('_state',None)
        deps['editor']=None if not obj.editor_id else {'id':obj.editor_id,'user':obj.editor.user_id,'username':obj.editor.user.username}
        return digest(deps)
    def apply(self,values,actor_id):
        if not transaction.get_connection().in_atomic_block:raise ValueError('workflow_transaction_required')
        obj,cleaned=self.cleaned(values,actor_id,True);actor=self.actor(actor_id)
        with external_effects_closed():
            if self.kind=='workflow':update_workflow(obj,cleaned,actor=actor)
            elif obj.status!=cleaned['status']:
                obj.status=cleaned['status'];obj.save(update_fields=['status'])
                sync_workflow_to_official_status(obj,actor=actor)
        return obj

WORKFLOWS={'video.status.transition':ProductionTransition('status'),'video.workflow.transition':ProductionTransition('workflow')}
