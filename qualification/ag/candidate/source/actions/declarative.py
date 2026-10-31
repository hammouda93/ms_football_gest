"""Reviewed scalar-form family. Definitions are code-owned, never client imports.
Full real forms validate the row; only selected reviewed columns are persisted.
"""
from dataclasses import dataclass
from datetime import date
from django import forms
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.core.serializers.json import DjangoJSONEncoder
import json
from .registry import SimpleFormAmendment
from gestion_joueurs.forms import PlayerForm
from gestion_joueurs.models import Player
from client_portal.forms import OrganizationForm
from client_portal.models import Organization
from prospects.forms import ProspectManagementForm
from prospects.models import Prospect

def scalar(value):
    return json.loads(json.dumps(value,cls=DjangoJSONEncoder,allow_nan=False))

@dataclass(frozen=True)
class ReviewedForm(SimpleFormAmendment):
    derived: tuple=()
    mode: str='amend'
    actor_field: str=''
    lookup_field: str='name'
    duplicate_fields: tuple=()
    def target(self,pk,actor_id,lock=False):
        if self.mode=='create':
            from django.contrib.auth.models import User
            if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():raise PermissionError('permission_denied')
            return self.model()
        return super().target(pk,actor_id,lock)
    def contract(self):
        form=self.form(data={})
        schema={}
        for name in self.fields:
            f=form.fields[name]
            if isinstance(f,(forms.ModelChoiceField,forms.FileField)):raise ValueError('unreviewed_form_field')
            if isinstance(f,forms.ChoiceField):
                rule={'type':'string','enum':[v for v,label in f.choices if v!='']}
            elif isinstance(f,forms.DateField):rule={'type':'string','format':'date'}
            elif isinstance(f,forms.CharField):rule={'type':'string','maxLength':min(f.max_length or 8000,8000)}
            else:raise ValueError('unreviewed_form_field')
            schema[name]=dict(rule,label=str(f.label or name),requiredByForm=f.required)
        return {'model':self.model._meta.label,'fields':(['id'] if self.mode=='amend' else [])+list(self.fields),'required':(['id'] if self.mode=='amend' else [k for k in self.fields if form.fields[k].required]),'schema':schema,
                'family':'reviewed_scalar_form/v1','sourceForm':self.form.__module__+'.'+self.form.__name__,
                'excludedFields':[f.attname for f in self.model._meta.concrete_fields if f.name not in self.fields and not (f.name=='age' and 'age_from_date_of_birth' in self.derived)],
                'calculatedFields':['age'] if 'age_from_date_of_birth' in self.derived else [],
                'excludedFormFields':[k for k in form.fields if k not in self.fields],
                'permission':'active_superuser + '+self.policy,'effects':['create_row' if self.mode=='create' else 'selected_columns_only',*self.derived],
                'excludedEffects':['external','access','accounts','emails','finance','jobs','status','conversion','production']}
    def cleaned(self,values,actor_id,lock=False):
        obj=self.target(values.get('id'),actor_id,lock)
        selected=set(values)-{'id'}
        if not selected:raise ValueError('empty_amendment')
        if selected-set(self.fields):raise ValueError('field_forbidden')
        data=model_to_dict(obj);data.update({k:v for k,v in values.items() if k!='id'})
        if self.mode=='create':
            selected=set(self.fields)
            if self.actor_field:setattr(obj,self.actor_field,actor_id)
        form=self.form(data=data,instance=obj)
        if not form.is_valid():raise ValueError('invalid_form')
        changes={k:form.cleaned_data[k] for k in sorted(selected)}
        for rule in self.derived:
            if rule!='age_from_date_of_birth':raise ValueError('unreviewed_derived_rule')
            # Player.save recalculates nonempty DOB on every save; persist and preview it.
            birth=obj.date_of_birth
            if birth:
                today=date.today();changes['age']=today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))
                # ModelForm excludes age; validate the final derived model value
                # on this isolated instance before preview, plan or persistence.
                obj.age=changes['age']
                try:obj.age=obj._meta.get_field('age').clean(obj.age,obj)
                except ValidationError:raise ValueError('invalid_model') from None
                changes['age']=obj.age
        return obj,changes
    def preview(self,step,actor_id):
        old=self.target(step['values'].get('id'),actor_id)
        obj,changes=self.cleaned(step['values'],actor_id)
        if self.mode=='create':
            new={f.attname:getattr(obj,f.attname) for f in obj._meta.concrete_fields if not f.primary_key and not getattr(f,'auto_now',False) and not getattr(f,'auto_now_add',False)}
            new.update(changes)
            return scalar({'as':step['as'],'op':step['op'],'id':None,'old':None,'new':new,'excluded':[],
                           'generated':[f.attname for f in obj._meta.concrete_fields if f.primary_key or getattr(f,'auto_now',False) or getattr(f,'auto_now_add',False)],'contract':self.contract()})
        return scalar({'as':step['as'],'op':step['op'],'id':old.pk,'old':{k:getattr(old,k) for k in changes},'new':changes,
                       'excluded':[f.attname for f in old._meta.concrete_fields if f.name not in changes],'contract':self.contract()})

    def lookup(self,prefix,limit,actor_id):
        from django.contrib.auth.models import User
        if self.mode!='amend':raise ValueError('lookup_forbidden')
        if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():raise PermissionError('permission_denied')
        qs=self.model.objects.filter(**{self.lookup_field+'__istartswith':prefix})
        if self.policy=='active_organization':qs=qs.filter(is_active=True)
        rows=list(qs.order_by('pk').values('id',self.lookup_field)[:limit+1])
        return {'rows':[{'id':r['id'],'label':r[self.lookup_field]} for r in rows[:limit]],'hasMore':len(rows)>limit,'limit':limit}
    def apply(self,values,actor_id):
        obj,changes=self.cleaned(values,actor_id,lock=True)
        if self.mode=='create' and self.duplicate_fields:
            filters={k:getattr(obj,k) for k in self.duplicate_fields}
            if self.model.objects.filter(**filters).exists():raise ValueError('duplicate_record')
        for k,v in changes.items():setattr(obj,k,v)
        obj.save(**({'update_fields':sorted(changes)} if self.mode=='amend' else {}))
        return obj

DEFINITIONS={
    'player.profile.create':ReviewedForm(Player,PlayerForm,('name','date_of_birth','club','league','position','whatsapp_number'),'new_player',('age_from_date_of_birth',),mode='create',duplicate_fields=('name','date_of_birth')),
    'organization.profile.create':ReviewedForm(Organization,OrganizationForm,('name','kind','contact_name','country','whatsapp_number'),'new_organization',mode='create',actor_field='created_by_id'),
    'organization.profile.amend':ReviewedForm(Organization,OrganizationForm,('name','contact_name','country','whatsapp_number'),'active_organization'),
    'prospect.profile.amend':ReviewedForm(Prospect,ProspectManagementForm,('full_name','date_of_birth','whatsapp_number','country','club','league','position','message','internal_notes'),'existing_prospect',lookup_field='full_name'),
    'player.profile.amend':ReviewedForm(Player,PlayerForm,('name','date_of_birth','club','league','position','whatsapp_number'),'existing_player',('age_from_date_of_birth',)),
}
