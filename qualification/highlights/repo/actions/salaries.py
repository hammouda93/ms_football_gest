"""Salary/expense orchestration delegates to the real add_expense view."""
from decimal import Decimal,InvalidOperation
from django.contrib.auth.models import User
from gestion_joueurs.models import Salary,Expense,Video,VideoEditor
from gestion_joueurs.forms import ExpenseForm
from .workflow import external_effects_closed
from .view_adapter import request_for
from .declarative import scalar

class SalaryRecord:
 model=Salary
 def contract(self):
  names=['editor','video','amount','salary_amount','date','description','salary_paid_status']
  form=ExpenseForm();schema={'editor':{'type':'integer'},'video':{'type':'integer'}}
  for name in names[2:]:
   f=form.fields[name];s={'type':'string','requiredByForm':f.required}
   if hasattr(f,'choices'):s['enum']=[v for v,l in f.choices]
   if hasattr(f,'decimal_places'):s.update(format='decimal',decimalPlaces=f.decimal_places,maxDigits=f.max_digits)
   schema[name]=s
  return {'model':'gestion_joueurs.Salary','fields':names,'required':names,'schema':schema,'family':'salary_orchestration/v1','sourceForm':'gestion_joueurs.forms.ExpenseForm','sourceView':'gestion_joueurs.views.add_expense','permission':'active_superuser + video_selected_for_editor','effects':['Salary','Expense','Video.salary_paid_status'],'excludedEffects':['provider_payment','external','messages','jobs'],'composition':'single_step_only','amountSemantics':'amount is expense; salary_amount is salary; preserved separately'}
 def cleaned(self,values,actor_id,lock=False):
  if not User.objects.filter(pk=actor_id,is_active=True,is_superuser=True).exists():raise PermissionError('permission_denied')
  eq=VideoEditor.objects.select_for_update() if lock else VideoEditor.objects
  editor=eq.get(pk=values['editor'])
  vq=Video.objects.select_for_update() if lock else Video.objects
  video=vq.get(pk=values['video'])
  if editor.pk!=video.editor_id:raise ValueError('salary_editor_video_mismatch')
  for n in ('amount','salary_amount'):
   try:
    amount=Decimal(values[n])
    if not amount.is_finite() or amount<=0:raise ValueError('invalid_salary_amount')
   except (InvalidOperation,TypeError):raise ValueError('invalid_salary_amount') from None
  if not values['date'] or not values['salary_paid_status']:raise ValueError('salary_required')
  data=dict(values,category='salary',video_editor=editor.pk)
  form=ExpenseForm(data,video_editor_id=editor.pk)
  if not form.is_valid():raise ValueError('invalid_salary_form')
  return video,(editor,form)
 def snapshot(self,values,actor_id,lock=False):
  video,(editor,form)=self.cleaned(values,actor_id,lock)
  from .readback import graph_salary,digest
  return digest(graph_salary(video.pk,editor.pk,'default',lock=lock))
 def preview(self,step,actor_id):
  v,(e,f)=self.cleaned(step['values'],actor_id);c=f.cleaned_data
  from .readback import graph_salary
  journal=graph_salary(v.pk,e.pk,'default')
  salaries={r['id']:r for g in journal.values() if g['model']=='gestion_joueurs.Salary' for r in g['rows']}
  expenses={r['id']:r for g in journal.values() if g['model']=='gestion_joueurs.Expense' for r in g['rows']}
  summary={'salary_count':len(salaries),'salary_amount':format(sum((Decimal(r['amount']) for r in salaries.values()),Decimal('0')),'.2f'),'expense_count':len(expenses),'expense_amount':format(sum((Decimal(r['amount']) for r in expenses.values()),Decimal('0')),'.2f')}
  financial={'before':summary,'after':{'salary_count':summary['salary_count']+1,'salary_amount':format(Decimal(summary['salary_amount'])+c['salary_amount'],'.2f'),'expense_count':summary['expense_count']+1,'expense_amount':format(Decimal(summary['expense_amount'])+c['amount'],'.2f')},'scope':'union target video or editor user; distinct IDs'}
  return scalar({'financial':financial,'as':step['as'],'op':step['op'],'id':None,'old':None,'new':{'user_id':e.user_id,'video_id':v.pk,'amount':c['salary_amount'],'created_by_id':actor_id,'date':self.model._meta.get_field('date').pre_save(self.model(),True)},'generated':['id'],'expense':{'category':'salary','amount':c['amount'],'date':c['date'],'description':c['description'],'created_by_id':actor_id},'video':{'id':v.pk,'old':v.salary_paid_status,'new':c['salary_paid_status']},'currency':'TND','externalPayment':False,'contract':self.contract()})
 def apply(self,values,actor_id):
  from gestion_joueurs.views import add_expense
  from contextlib import redirect_stdout
  import io
  v,(e,f)=self.cleaned(values,actor_id,True)
  # Real DateField.pre_save on an unsaved object: host date.today(), no DB write.
  # Expense.date remains the explicit form date; do not change the legacy rule.
  expected_date=self.model._meta.get_field('date').pre_save(self.model(),True)
  # Legacy view prints POST/cleaned data. Never allow it into action logs.
  prior=set(Salary.objects.filter(video=v).values_list('pk',flat=True))
  with external_effects_closed(),redirect_stdout(io.StringIO()):
   response=add_expense(request_for(actor_id,dict(values,category='salary',video_editor=e.pk)))
  if response.status_code!=302:raise ValueError('salary_view_failed')
  inserted=list(Salary.objects.filter(video=v).exclude(pk__in=prior))
  if len(inserted)!=1:raise ValueError('salary_result_ambiguous')
  if inserted[0].date!=expected_date:raise ValueError('salary_date_conflict')
  return inserted[0]

SALARIES={'finance.salary.record':SalaryRecord()}
