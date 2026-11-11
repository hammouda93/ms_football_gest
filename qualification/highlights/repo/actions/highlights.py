"""Reviewed Highlights terms: real VideoForm and fixed application views.

A package always owns its tariff. A direct order can carry a custom tariff,
not a fabricated package. No account, message, automation or external effect.
"""
from decimal import Decimal, InvalidOperation
from django.contrib.auth.models import User
from django.forms.models import model_to_dict
from gestion_joueurs.forms import VideoForm
from gestion_joueurs.models import Video, Player, Invoice, Payment
from .view_adapter import request_for
from .declarative import scalar

TERMS=('editor','total_payment','advance_payment','season','whatsapp_conversation_date','deadline_from_whatsapp','deadline','info','client_organization','match_package')

def money(value):
    try:
        n=Decimal(value)
        if not n.is_finite() or n<0 or n>Decimal('99999999.99') or n!=n.quantize(Decimal('.01')):raise ValueError()
    except (ValueError,TypeError,InvalidOperation):raise ValueError('invalid_money') from None
    return n

def notification(video,actor,created=False):
    editor=video.editor
    if editor.user_id==actor or (not created and editor.user.is_superuser):return []
    return [dict(user_id=editor.user_id,message=f'Vous avez été assigné à une nouvelle vidéo : {video}',notification_type='inter_user' if created else 'update',sent_by_id=actor,player_id=video.player_id,is_read=False)]

class HighlightCreate:
    model=Video
    def contract(self):
        fields=['player',*TERMS]
        form=VideoForm()
        schema={k:{'type':'boolean' if k=='deadline_from_whatsapp' else 'integer' if k in ('player','editor','client_organization','match_package') else 'string'} for k in fields}
        model_seasons={v for v,_ in Video._meta.get_field('season').choices}
        schema['season']['enum']=[v for v,_ in form.fields['season'].choices if v in model_seasons]
        schema['match_package']['enum']=[v for v,_ in form.fields['match_package'].choices if v!='']
        return dict(model=Video._meta.label,fields=fields,required=['player',*TERMS[:8]],schema=schema,
                    family='highlight_conditions/v1',sourceForm='gestion_joueurs.forms.VideoForm',sourceView='gestion_joueurs.views.create_video_highlight',
                    permission='active_superuser',preconditions=['single_step','exact_package_price_or_direct_custom_price','explicit_deadline','nonnegative_money'],
                    effects=['video','invoice','initial_payment_if_positive','history','internal_assignment_notification'],excludedEffects=['external','email','access','jobs'])
    def target(self,pk,actor_id,lock=False):
        if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():raise PermissionError('permission_denied')
        qs=Video.objects.select_for_update() if lock else Video.objects
        return qs.get(pk=pk)
    def cleaned(self,values,actor_id,lock=False):
        actor=User.objects.get(pk=actor_id,is_active=True,is_superuser=True)
        price=money(values['total_payment']);money(values['advance_payment'])
        player=Player.objects.get(pk=values['player'])
        data={k:v for k,v in values.items() if k!='player'}
        data.update(status='pending',seasons_to_process=1,matches_processed=0,client_portal_visible=False)
        f=VideoForm(data,user=actor,player=player)
        try:valid=f.is_valid()
        except OverflowError:raise ValueError('invalid_deadline') from None
        if not valid:raise ValueError('invalid_video_conditions')
        if f.cleaned_data['editor'].user_id is None:raise ValueError('editor_user_required')
        if not f.cleaned_data['deadline']:raise ValueError('deadline_required')
        if f.cleaned_data['total_payment']!=price:raise ValueError('package_price_mismatch')
        if f.cleaned_data['deadline'].isoformat()!=values['deadline']:raise ValueError('deadline_mismatch')
        if Video.objects.filter(player=player,season=values['season'],client_organization=f.cleaned_data['client_organization']).exists():raise ValueError('duplicate_order')
        obj=f.instance;obj.player=player;obj.club=player.club;obj.league=player.league
        new=scalar({field.attname:getattr(obj,field.attname) for field in Video._meta.concrete_fields if field.name not in ('id','video_creation_date','intro_photo')})
        new['intro_photo']=''
        new['total_payment']=format(obj.total_payment,'.2f');new['advance_payment']=format(obj.advance_payment,'.2f')
        return obj,new
    def preview(self,step,actor_id):
        obj,new=self.cleaned(step['values'],actor_id)
        price=obj.total_payment;advance=obj.advance_payment
        status='paid' if price>0 and advance>=price else 'partially_paid' if advance>0 else 'unpaid'
        return {'as':step['as'],'op':step['op'],'old':None,'new':new,'generated':['id','video_creation_date'],
            'invoice':dict(total_amount=format(price,'.2f'),amount_paid=format(advance,'.2f'),status=status,created_by_id=actor_id,payment_method=None),
            'payment':dict(player_id=obj.player_id,amount=format(advance,'.2f'),payment_type='final' if advance>=price else 'advance',created_by_id=actor_id,remaining_balance=format(price-advance,'.2f'),payment_method=None) if advance>0 else None,
            'history':[dict(editor_id=obj.editor_id,status='pending',comment='Video created.',created_by_id=actor_id)],'notifications':notification(obj,actor_id,True),'currency':'TND','contract':self.contract()}
    def apply(self,values,actor_id):
        obj,new=self.cleaned(values,actor_id,True)
        from gestion_joueurs.views import create_video_highlight
        data={k:v for k,v in values.items() if k!='player'}
        data.update(player=values['player'],create_video='1',status='pending',seasons_to_process=1,matches_processed=0)
        # HTML checkboxes are omitted when false (RequestFactory encodes False as text).
        if not data['deadline_from_whatsapp']:data.pop('deadline_from_whatsapp')
        response=create_video_highlight(request_for(actor_id,data))
        if response.status_code!=302:raise ValueError('order_view_failed')
        return Video.objects.get(player_id=values['player'],season=values['season'],client_organization_id=values.get('client_organization'))

class HighlightAmend(HighlightCreate):
    def contract(self):
        c=super().contract();c['fields']=['id',*TERMS];c['required']=['id'];c['schema'].pop('player');c['schema']['id']={'type':'integer'}
        c['sourceView']='gestion_joueurs.views.edit_video';c['effects']=['video_terms','invoice_total_and_status','internal_assignment_notification']
        c['preconditions'] += ['existing_invoice','advance_immutable_use_payment_record_for_new_money']
        return c
    def cleaned(self,values,actor_id,lock=False):
        obj=self.target(values['id'],actor_id,lock)
        history=list(obj.status_history.order_by('-changed_at')[:2])
        if not history or history[0].status!=obj.status or (len(history)>1 and history[0].changed_at==history[1].changed_at):raise ValueError('history_status_conflict')
        if len(values)==1:raise ValueError('empty_amendment')
        invoice=(Invoice.objects.select_for_update() if lock else Invoice.objects).get(video=obj)
        if 'advance_payment' in values and money(values['advance_payment'])!=obj.advance_payment:raise ValueError('advance_immutable_use_payment_record')
        for k in ('total_payment','advance_payment'):
            if k in values:money(values[k])
        data=model_to_dict(obj);data.update({k:v for k,v in values.items() if k!='id'})
        f=VideoForm(data,instance=obj,user=User.objects.get(pk=actor_id))
        try:valid=f.is_valid()
        except OverflowError:raise ValueError('invalid_deadline') from None
        if not valid:raise ValueError('invalid_video_conditions')
        if f.cleaned_data['editor'].user_id is None:raise ValueError('editor_user_required')
        if not obj.deadline:raise ValueError('deadline_required')
        if obj.total_payment!=money(str(data['total_payment'])):raise ValueError('package_price_mismatch')
        if 'deadline' in values and obj.deadline.isoformat()!=values['deadline']:raise ValueError('deadline_mismatch')
        new=scalar({field.attname:getattr(obj,field.attname) for field in Video._meta.concrete_fields if field.name in TERMS})
        new['total_payment']=format(obj.total_payment,'.2f');new['advance_payment']=format(obj.advance_payment,'.2f')
        return obj,new
    def snapshot(self,values,actor_id,lock=False):
        import hashlib,json
        self.cleaned(values,actor_id,lock)
        out={}
        for name,qs in [('video',Video.objects.filter(pk=values['id'])),('invoice',Invoice.objects.filter(video_id=values['id'])),('payments',Payment.objects.filter(video_id=values['id']).order_by('pk'))]:
            if lock:qs=qs.select_for_update()
            out[name]=list(qs.values()[:257])
            if len(out[name])>256:raise ValueError('dependency_limit')
        return hashlib.sha256(json.dumps(out,sort_keys=True,default=str).encode()).hexdigest()
    def preview(self,step,actor_id):
        old=self.target(step['values']['id'],actor_id);obj,new=self.cleaned(step['values'],actor_id)
        invoice=Invoice.objects.get(video=old)
        status='unpaid' if invoice.amount_paid==0 else 'partially_paid' if invoice.amount_paid<obj.total_payment else 'paid'
        from django.db.models import Sum
        journal=Payment.objects.filter(video=old).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        financial_old=dict(total_amount=format(invoice.total_amount,'.2f'),amount_paid=format(invoice.amount_paid,'.2f'),payment_journal_total=format(journal,'.2f'),remaining_balance=format(invoice.total_amount-invoice.amount_paid,'.2f'),status=invoice.status)
        financial_new=financial_old|dict(total_amount=format(obj.total_payment,'.2f'),remaining_balance=format(obj.total_payment-invoice.amount_paid,'.2f'),status=status)
        return {'as':step['as'],'op':step['op'],'old':scalar({k:getattr(old,k) for k in new}),'new':new,
                'invoice':{'id':invoice.pk,'old':{k:v for k,v in financial_old.items() if k not in ('payment_journal_total','remaining_balance')},'new':{k:v for k,v in financial_new.items() if k not in ('payment_journal_total','remaining_balance')}},
                'financial':{'old':financial_old,'new':financial_new},
                'notifications':notification(obj,actor_id) if old.editor_id!=obj.editor_id else [],'currency':'TND','contract':self.contract()}
    def apply(self,values,actor_id):
        obj,new=self.cleaned(values,actor_id,True)
        from gestion_joueurs.views import edit_video
        data={k:v for k,v in model_to_dict(obj).items() if v is not None and k in VideoForm._meta.fields}
        for k in ('deadline_from_whatsapp','client_portal_visible'):
            if not data.get(k):data.pop(k,None)
        response=edit_video(request_for(actor_id,data),obj.pk)
        if response.status_code!=302:raise ValueError('amend_view_failed')
        return Video.objects.get(pk=obj.pk)

HIGHLIGHTS={'video.conditions.create':HighlightCreate(),'video.conditions.amend':HighlightAmend()}
