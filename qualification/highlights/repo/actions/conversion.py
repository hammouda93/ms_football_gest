"""Reuse the actual conversion service; preview detached, never save in prepare."""
import copy,json,hashlib
from datetime import date
from django.contrib.auth.models import User
from django.db.models import Q
from gestion_joueurs.models import Player
from prospects.models import Prospect
from prospects.services import PROSPECT_TO_PLAYER_POSITION,find_matching_player,convert_prospect_to_player
from .declarative import scalar

class Conversion:
    model=Prospect
    def contract(self):
        return {'model':Prospect._meta.label,'fields':['id'],'required':['id'],'schema':{'id':{'type':'integer'}},'family':'prospect_conversion/v1','permission':'active_superuser','sourceService':'prospects.services.convert_prospect_to_player','effects':['find_or_create_or_enrich_player','prospect_converted'],'excludedEffects':['video','invoice','accounts','external','jobs'],'result':'prospect ID; player ID verified in linked row; no player alias'}
    def target(self,pk,actor_id,lock=False):
        if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():raise PermissionError('permission_denied')
        qs=Prospect.objects.select_for_update() if lock else Prospect.objects
        return qs.get(pk=pk)
    def candidates(self,p,lock=False):
        q=Q(pk=p.player_id) if p.player_id else Q(pk__in=[])
        if p.transfermarkt_url:q |= Q(transfermarkt_url__iexact=p.transfermarkt_url)
        if p.date_of_birth:q |= Q(name__iexact=p.full_name,date_of_birth=p.date_of_birth)
        if p.club:q |= Q(name__iexact=p.full_name,club__iexact=p.club)
        qs=Player.objects.filter(q).order_by('pk')
        if lock:qs=qs.select_for_update()
        found=list(qs[:3])
        if len(found)>1:raise ValueError('conversion_identity_ambiguous')
        return found
    def cleaned(self,values,actor_id,lock=False):
        p=self.target(values['id'],actor_id,lock);self.candidates(p,lock)
        self.project(p)
        return p,{}
    def project(self,p):
        player=p.player or find_matching_player(p)
        old=copy.copy(player) if player else None
        if not player:
            player=Player(name=p.full_name,club=p.club,email=p.email,date_of_birth=p.date_of_birth,whatsapp_number=p.whatsapp_number,league=p.league,position=PROSPECT_TO_PLAYER_POSITION.get(p.position,'DF'),transfermarkt_url=p.transfermarkt_url or None)
            selected=['name','club','email','date_of_birth','whatsapp_number','league','position','transfermarkt_url']
        else:
            player=copy.copy(player);selected=[]
            for k in ('email','date_of_birth','whatsapp_number','transfermarkt_url'):
                if getattr(p,k) and not getattr(player,k):setattr(player,k,getattr(p,k));selected.append(k)
        if player.date_of_birth and (old is None or 'date_of_birth' in selected):
            today=date.today();player.age=today.year-player.date_of_birth.year-((today.month,today.day)<(player.date_of_birth.month,player.date_of_birth.day));selected.append('age')
        player.full_clean()
        if old is None:
            new={f.attname:getattr(player,f.attname) for f in Player._meta.concrete_fields if not f.primary_key and f.name!='player_creation_date'}
        else:new={k:getattr(player,k) for k in selected}
        return old,player,scalar(new)
    def preview(self,step,actor_id):
        p,_=self.cleaned(step['values'],actor_id);old,player,new=self.project(p)
        return {'as':step['as'],'op':step['op'],'id':p.pk,'old':{'status':p.status,'player_id':p.player_id},'new':{'status':'converted'},'player':{'id':None if old is None else old.pk,'new':new,'create':old is None},'contract':self.contract()}
    def snapshot(self,values,actor_id,lock=False):
        p=self.target(values['id'],actor_id,lock);found=self.candidates(p,lock)
        def row(o):return {f.attname:getattr(o,f.attname) for f in o._meta.concrete_fields}
        return hashlib.sha256(json.dumps({'prospect':row(p),'players':[row(o) for o in found]},sort_keys=True,default=str).encode()).hexdigest()
    def apply(self,values,actor_id):
        p,_=self.cleaned(values,actor_id,True)
        convert_prospect_to_player(p)
        return p

CONVERSIONS={'prospect.convert':Conversion()}
