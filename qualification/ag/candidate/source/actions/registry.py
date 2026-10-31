"""Explicit, server-owned registry. Never accepts a client model/form/callable."""
from dataclasses import dataclass
import hashlib,json
from django import forms
from django.forms.models import model_to_dict
from django.contrib.auth.models import User
from client_portal.forms import OrganizationForm
from client_portal.models import Organization
from prospects.forms import ProspectManagementForm
from prospects.models import Prospect

LEGACY={
 'player.create':{'model':'gestion_joueurs.Player','fields':['name','club','league','position','date_of_birth'],'required':['name','club','league','position','date_of_birth']},
 'organization.link':{'model':'client_portal.OrganizationPlayer','fields':['player','organization','expected_matches'],'required':['player','organization','expected_matches']},
 'video.order':{'model':'gestion_joueurs.Video','fields':['player','editor','client_organization','whatsapp_conversation_date','deadline_from_whatsapp','match_package','season','advance_payment','info'],'required':['player','editor','client_organization','whatsapp_conversation_date','deadline_from_whatsapp','match_package','season','advance_payment','info']},
 'player.amend':{'model':'gestion_joueurs.Player','fields':['id','club','position'],'required':['id']},
 'video.amend':{'model':'gestion_joueurs.Video','fields':['id','info'],'required':['id','info']}}

@dataclass(frozen=True)
class SimpleFormAmendment:
    model: object
    form: object
    fields: tuple
    policy: str
    def target(self,pk,actor_id,lock=False):
        if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():
            raise PermissionError('permission_denied')
        qs=self.model.objects.select_for_update() if lock else self.model.objects
        try:obj=qs.get(pk=pk)
        except self.model.DoesNotExist:raise ValueError('target_missing') from None
        if self.policy=='active_organization' and not obj.is_active:raise PermissionError('object_permission_denied')
        return obj
    def contract(self):
        form=self.form()
        schema={}
        for name in self.fields:
            field=form.fields[name]
            if not isinstance(field,forms.CharField) or isinstance(field,(forms.ModelChoiceField,forms.FileField)):
                raise ValueError('unreviewed_form_field')
            rule={'type':'string','label':str(field.label or name),'requiredByForm':field.required,'maxLength':min(getattr(field,'max_length',None) or 8000,8000)}
            if isinstance(field,forms.ChoiceField):rule['enum']=[v for v,label in field.choices if v!='']
            schema[name]=rule
        return {'model':self.model._meta.label,'fields':['id',*self.fields],'required':['id'],
                'schema':schema,'family':'simple_form_amendment/v1','permission':'active_superuser + '+self.policy,
                'effects':['selected_columns_only'],'excludedEffects':['external','access','finance','jobs'],
                'sourceForm':self.form.__module__+'.'+self.form.__name__}
    def cleaned(self,values,actor_id,lock=False):
        obj=self.target(values['id'],actor_id,lock)
        selected=set(values)-{'id'}
        if not selected:raise ValueError('empty_amendment')
        if selected-set(self.fields):raise ValueError('field_forbidden')
        data=model_to_dict(obj)
        data.update({k:v for k,v in values.items() if k!='id'})
        form=self.form(data=data,instance=obj)
        if not form.is_valid():raise ValueError('invalid_form')
        changes={k:form.cleaned_data[k] for k in selected}
        return obj,changes
    def preview(self,step,actor_id):
        old=self.target(step['values']['id'],actor_id)
        obj,changes=self.cleaned(step['values'],actor_id)
        return {'as':step['as'],'op':step['op'],'id':old.pk,
                'old':{k:getattr(old,k) for k in changes},'new':changes,
                'excluded':[f.attname for f in old._meta.concrete_fields if f.name not in changes],
                'contract':self.contract()}
    def apply(self,values,actor_id):
        obj,changes=self.cleaned(values,actor_id,lock=True)
        for k,v in changes.items():setattr(obj,k,v)
        obj.save(update_fields=sorted(changes))
        return obj

SIMPLE={
 'organization.details.amend':SimpleFormAmendment(Organization,OrganizationForm,('name','contact_name','country'),'active_organization'),
 'prospect.details.amend':SimpleFormAmendment(Prospect,ProspectManagementForm,('internal_notes','country','club'),'existing_prospect')
}

from .declarative import DEFINITIONS
SIMPLE.update(DEFINITIONS)

def catalogue():
    from copy import deepcopy
    from .workflow import WORKFLOWS
    return {**deepcopy(LEGACY),**{op:adapter.contract() for op,adapter in SIMPLE.items()},**{op:adapter.contract() for op,adapter in WORKFLOWS.items()}}
