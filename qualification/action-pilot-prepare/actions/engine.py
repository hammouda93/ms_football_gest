"""Server-owned composable business adapters, not arbitrary ORM CRUD."""
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist,ValidationError
from gestion_joueurs.forms import PlayerForm,VideoForm
from gestion_joueurs.models import Player,Video,VideoEditor,Invoice
from gestion_joueurs.views import _associate_player_organization
from client_portal.models import Organization,OrganizationPlayer
from .models import Plan

class Engine:
    def __init__(self,actor_id): self.actor_id=actor_id
    def authorize(self):
        from django.contrib.auth.models import User
        from .models import Audit
        if not User.objects.filter(pk=self.actor_id,is_active=True,is_superuser=True).exists():
            Audit.objects.create(actor_id=self.actor_id,event='refused',code='permission_denied')
            raise PermissionError('permission_denied')
    def catalogue(self):
        return {
          'player.create':{'model':'gestion_joueurs.Player','fields':['name','club','league','position','date_of_birth'],'required':['name','club','league','position','date_of_birth']},
          'organization.link':{'model':'client_portal.OrganizationPlayer','fields':['player','organization','expected_matches'],'required':['player','organization','expected_matches']},
          'video.order':{'model':'gestion_joueurs.Video','fields':['player','editor','client_organization','whatsapp_conversation_date','deadline_from_whatsapp','match_package','season','advance_payment','info'],'required':['player','editor','client_organization','whatsapp_conversation_date','deadline_from_whatsapp','match_package','season','advance_payment','info']},
          'player.amend':{'model':'gestion_joueurs.Player','fields':['id','club','position'],'required':['id']},
          'video.amend':{'model':'gestion_joueurs.Video','fields':['id','info'],'required':['id','info']}}
    def validate(self,steps):
        import json,re
        if not isinstance(steps,list) or not 1<=len(steps)<=12 or len(json.dumps(steps))>24000:raise ValueError('invalid_plan')
        seen={}
        relations={'player':'gestion_joueurs.Player'}
        for s in steps:
            if not isinstance(s,dict) or set(s)!={'as','op','values'}:raise ValueError('invalid_step')
            if not isinstance(s['op'],str) or s['op'] not in self.catalogue():raise ValueError('operation_forbidden')
            if not isinstance(s['as'],str) or not re.fullmatch('[a-z][a-z0-9_]{0,31}',s['as']) or s['as'] in seen:raise ValueError('invalid_alias')
            rule=self.catalogue()[s['op']];v=s['values']
            if not isinstance(v,dict) or set(v)-set(rule['fields']):raise ValueError('field_forbidden')
            if set(rule['required'])-set(v):raise ValueError('missing_field')
            for k,x in v.items():
                if isinstance(x,dict):
                    if set(x)!={'ref'} or not isinstance(x['ref'],str) or x['ref'] not in seen or k not in relations or seen[x['ref']]!=relations[k]:raise ValueError('invalid_reference')
                elif not isinstance(x,(str,int,bool)) or x is None:raise ValueError('invalid_value')
                else:
                    expected=bool if k=='deadline_from_whatsapp' else (int if k in ('id','player','organization','editor','client_organization','match_package','expected_matches') else str)
                    if type(x) is not expected:raise ValueError('invalid_type')
                    if expected is int and x<=0:raise ValueError('invalid_type')
                    if expected is str and len(x)>8000:raise ValueError('invalid_value')
            if s['op']=='video.order':self.payment(v['advance_payment'])
            seen[s['as']]=rule['model']
    @staticmethod
    def payment(value,require_zero=False):
        from decimal import Decimal,InvalidOperation
        try:
            advance=Decimal(value)
            if not advance.is_finite() or (require_zero and advance!=0):
                raise ValueError('payment_not_supported')
        except (InvalidOperation,TypeError,ValueError):
            raise ValueError('payment_not_supported') from None
        return advance
    def prepare(self,key,steps):
        self.authorize()
        from .models import Audit
        try:self.validate(steps)
        except ValueError as exc:
            Audit.objects.create(actor_id=self.actor_id,event='refused',code=str(exc));raise
        import hashlib,json,re
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',key):raise ValueError('invalid_key')
        digest=hashlib.sha256(json.dumps(steps,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with transaction.atomic():
            p,created=Plan.objects.get_or_create(actor_id=self.actor_id,key=key,defaults={'digest':digest,'steps':steps})
            if p.steps!=steps:raise ValueError('idempotency_mismatch')
            if created:
                p.snapshots=self.snapshots(steps);p.digest=self.proposal_digest(p.steps,p.snapshots);p.save(update_fields=['snapshots','digest'])
                Audit.objects.create(plan=p,actor_id=self.actor_id,event='prepared')
        return self.status(p.pk)
    def snapshots(self,steps,lock=False):
        import hashlib,json
        out={'__preview__':self.preview(steps)}
        for s in steps:
            if s['op'] in ('player.amend','video.amend'):
                model=Player if s['op']=='player.amend' else Video
                qs=model.objects.select_for_update() if lock else model.objects
                try:row=qs.values().get(pk=s['values']['id'])
                except model.DoesNotExist:raise ValueError('target_missing')
                out[s['as']]=hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
        # Only player.create aliases are new rows; player.amend aliases name
        # existing players and must carry the same dependencies as literal IDs.
        existing_players={s['as']:s['values']['id'] for s in steps if s['op']=='player.amend'}
        def concrete(value):
            return existing_players.get(value['ref']) if isinstance(value,dict) else value
        # Snapshot concrete players, editors/users and organizations.
        for s in steps:
            for field,model in [('player',Player),('organization',Organization),('client_organization',Organization),('editor',VideoEditor)]:
                pk=concrete(s['values'].get(field))
                if type(pk) is not int:continue
                qs=model.objects.select_for_update() if lock else model.objects
                row=qs.values().filter(pk=pk).first()
                out[model._meta.label+':'+str(pk)]=hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
                if model is VideoEditor and row:
                    from django.contrib.auth.models import User
                    users=User.objects.select_for_update() if lock else User.objects
                    u=users.values().filter(pk=row['user_id']).first()
                    out['auth.User:'+str(row['user_id'])]=hashlib.sha256(json.dumps(u,sort_keys=True,default=str).encode()).hexdigest()
        for s in steps:
            if s['op'] not in ('organization.link','video.order'):continue
            v=s['values'];player=concrete(v.get('player'));organization=v.get('organization',v.get('client_organization'))
            if type(player) is not int or type(organization) is not int:continue
            links=OrganizationPlayer.objects.filter(player_id=player,organization_id=organization).order_by('pk')
            if lock:links=links.select_for_update()
            rows=list(links.values())
            out['membership:'+str(player)+':'+str(organization)]=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
        return out
    def preview(self,steps):
        from datetime import date,timedelta
        orders=[]
        for s in steps:
            if s['op']=='video.order':
                v=s['values']
                try:deadline=(date.fromisoformat(v['whatsapp_conversation_date'])+timedelta(days=5)).isoformat()
                except OverflowError:raise ValueError('invalid_deadline') from None
                except ValueError:deadline=None
                from decimal import Decimal
                price=Video.MATCH_PACKAGE_PRICES.get(v['match_package'])
                orders.append({'as':s['as'],'price':format(Decimal(str(price)),'.2f') if price is not None else None,'advance_payment':v['advance_payment'],'deadline':deadline,'effects':['video','invoice','history','possible_internal_notification']})
        return {'operations':steps,'orders':orders}
    @staticmethod
    def proposal_digest(steps,snapshots):
        import hashlib,json
        return hashlib.sha256(json.dumps({'steps':steps,'preconditions':snapshots},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    def status(self,plan_id):
        self.authorize()
        p=Plan.objects.get(pk=plan_id,actor_id=self.actor_id)
        return {'id':str(p.pk),'state':p.state,'results':p.results,'error':p.error,'effects':p.effects}
    def execute(self,plan_id):
        self.authorize()
        from django.contrib.auth.models import User
        actor=User.objects.get(pk=self.actor_id)
        with transaction.atomic():
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_xact_lock(41001,1)')
                if not cursor.fetchone()[0]:raise ValueError('busy')
            p=Plan.objects.select_for_update().get(pk=plan_id,actor_id=self.actor_id)
            if p.state!='prepared':return self.status(p.pk)
            self.validate(p.steps)
            import hashlib,json
            if self.proposal_digest(p.steps,p.snapshots)!=p.digest:raise ValueError('plan_integrity')
            try:
                with transaction.atomic():
                    if self.snapshots(p.steps,lock=True)!=p.snapshots:raise ValueError('conflict')
                    from gestion_joueurs.utils import actor_context
                    from .effects import effects_context
                    with actor_context(actor), effects_context() as effects:
                        results=self._apply(p.steps,actor)
            except (ValueError,ObjectDoesNotExist,ValidationError) as exc:
                code='target_missing' if isinstance(exc,ObjectDoesNotExist) else ('invalid_model' if isinstance(exc,ValidationError) else str(exc))
                p.state='failed';p.error=code;p.results={};p.save()
                from .models import Audit
                Audit.objects.create(plan=p,actor_id=self.actor_id,event='failed',code=p.error)
            else:
                p.state='succeeded';p.results=results;p.effects=effects;p.save()
                from .models import Audit
                Audit.objects.create(plan=p,actor_id=self.actor_id,event='succeeded')
        return self.status(p.pk)
    def _apply(self,steps,actor):
            results={}
            for step in steps:
                values={k:(results[v['ref']] if isinstance(v,dict) else v) for k,v in step['values'].items()}
                if step['op']=='player.create':
                    if Player.objects.filter(name__iexact=values['name'].strip(),date_of_birth=values['date_of_birth']).exists():raise ValueError('duplicate_player')
                    f=PlayerForm(values)
                    if not f.is_valid():raise ValueError('invalid_player')
                    obj=f.save()
                elif step['op']=='organization.link':
                    if type(values['expected_matches']) is not int or values['expected_matches'] not in (3,5,10):raise ValueError('invalid_link')
                    org=Organization.objects.get(pk=values['organization'],is_active=True,kind__in=['agent','academy'])
                    obj=_associate_player_organization(player=Player.objects.get(pk=values['player']),organization=org,user=actor)
                    obj.expected_matches=values['expected_matches'];obj.save()
                elif step['op']=='video.order':
                    advance=self.payment(values['advance_payment'],require_zero=True)
                    if values['deadline_from_whatsapp'] is not True:raise ValueError('automatic_deadline_required')
                    player=Player.objects.get(pk=values.pop('player'))
                    if Video.objects.filter(player=player,season=values['season'],client_organization_id=values['client_organization']).exists():raise ValueError('duplicate_order')
                    if not OrganizationPlayer.objects.filter(player=player,organization_id=values['client_organization'],is_active=True,expected_matches=values['match_package'],organization__is_active=True).exists():raise ValueError('organization_link_mismatch')
                    f=VideoForm(dict(values,status='pending',total_payment='0',seasons_to_process=1,matches_processed=0),user=actor,player=player)
                    if not f.is_valid():raise ValueError('invalid_video')
                    obj=f.save(commit=False);obj.player=player;obj.club=player.club;obj.league=player.league;obj.save()
                    Invoice.objects.create(video=obj,total_amount=obj.total_payment,amount_paid=obj.advance_payment,status='unpaid',created_by=actor)
                elif step['op']=='player.amend':
                    obj=Player.objects.get(pk=values.pop('id'))
                    for k,v in values.items():setattr(obj,k,v)
                    obj.full_clean(exclude=['email']);obj.save()
                elif step['op']=='video.amend':
                    obj=Video.objects.get(pk=values.pop('id'))
                    obj.info=values['info'];obj.full_clean();obj.save(update_fields=['info'])
                results[step['as']]=obj.pk
            return results
