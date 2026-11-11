"""Closed internal registration contracts. No provider payment or external I/O."""
from django.contrib.auth.models import User
from gestion_joueurs.models import NonVideoIncome,Expense
from gestion_joueurs.forms import NonVideoIncomeForm,ExpenseForm
from .declarative import ReviewedForm,scalar
from decimal import Decimal,InvalidOperation
from sportsbase_data.models import SportsBaseSubscription,PerformanceSubscriptionPayment
from sportsbase_data.forms import PerformanceSubscriptionPaymentForm

def financial_projection(kind,parent,journal,amount=Decimal('0.00')):
    """Closed financial context from bounded journal; no provider observation."""
    total=Decimal(parent['total_amount'])
    journal_paid=sum((Decimal(r['amount']) for r in journal),Decimal('0.00'))+amount
    paid=journal_paid if kind=='performance' else Decimal(parent['amount_paid'])+amount
    remaining=max(Decimal('0.00'),total-paid) if kind=='performance' else total-paid
    state=('not_configured' if total<=0 else 'paid' if remaining<=0 else 'partial' if paid>0 else 'unpaid') if kind=='performance' else ('paid' if paid>=total else 'partially_paid' if paid>0 else 'unpaid')
    money=lambda x:format(x,'.2f')
    return {'total_amount':money(total),'currency':parent['currency'] if kind=='performance' else 'TND','amount_paid':money(paid),'remaining_balance':money(remaining),'payment_state':state,'journal_amount_paid':money(journal_paid)}

class InternalRecord(ReviewedForm):
    def preview(self,step,actor_id):
        x=super().preview(step,actor_id)
        if self.model is PerformanceSubscriptionPayment:
            sub=SportsBaseSubscription.objects.get(pk=step['values']['subscription'])
            journal=list(sub.payments.order_by('pk').values('amount')[:257])
            if len(journal)>256:raise ValueError('dependency_limit')
            parent={'total_amount':sub.total_amount,'currency':sub.currency}
            x['financial']={'before':financial_projection('performance',parent,journal),'after':financial_projection('performance',parent,journal,Decimal(step['values']['amount']))}
        return x
    def contract(self):
        form=self.form()
        schema={}
        from django import forms
        for name in self.fields:
            f=form.fields[name]
            r={'type':'string','requiredByForm':f.required}
            if isinstance(f,forms.DecimalField):r.update(format='decimal',maxDigits=f.max_digits,decimalPlaces=f.decimal_places)
            elif isinstance(f,forms.DateField):r['format']='date'
            elif isinstance(f,forms.ChoiceField):r['enum']=[v for v,l in f.choices if v!='']
            elif not isinstance(f,forms.CharField):raise ValueError('unreviewed_form_field')
            schema[name]=r
        if self.model is PerformanceSubscriptionPayment:schema['subscription']={'type':'integer'}
        names=list(self.fields)+(['subscription'] if self.model is PerformanceSubscriptionPayment else [])
        return {'model':self.model._meta.label,'fields':names,'required':names,'schema':schema,'family':'internal_registration/v1','permission':'active_superuser','sourceForm':self.form.__module__+'.'+self.form.__name__,'effects':['application_record_only'],'excludedEffects':['provider_payment','external','accounts','jobs','publication','delivery']}
    def cleaned(self,values,actor_id,lock=False):
        obj=self.target(None,actor_id,lock)
        if 'date' in self.fields and not values.get('date'):raise ValueError('date_required')
        if self.model is Expense and values.get('category')=='salary':raise ValueError('salary_orchestration_required')
        try:
            amount=Decimal(values['amount'])
            if not amount.is_finite() or amount<=0:raise ValueError('invalid_amount')
        except (InvalidOperation,TypeError):raise ValueError('invalid_amount') from None
        # Validate amount first: the application's income clean assumes a Decimal.
        if not self.form().fields['amount'].clean(values['amount']):raise ValueError('invalid_amount')
        kwargs={}
        if self.model is PerformanceSubscriptionPayment:
            qs=SportsBaseSubscription.objects.select_for_update() if lock else SportsBaseSubscription.objects
            sub=qs.get(pk=values['subscription']);obj.subscription=sub;kwargs['subscription']=sub
        form=self.form(data=values,instance=obj,**kwargs)
        if not form.is_valid():raise ValueError('invalid_form')
        obj.created_by_id=actor_id
        changes={k:form.cleaned_data[k] for k in self.fields}
        changes['created_by_id']=actor_id
        if self.model is PerformanceSubscriptionPayment:changes['subscription_id']=sub.pk
        return obj,changes

    def snapshot(self,values,actor_id,lock=False):
        self.target(None,actor_id)
        if self.model is not PerformanceSubscriptionPayment:return None
        qs=SportsBaseSubscription.objects.filter(pk=values['subscription'])
        payments=PerformanceSubscriptionPayment.objects.filter(subscription_id=values['subscription']).order_by('pk')
        if lock:qs=qs.select_for_update();payments=payments.select_for_update()
        result={'subscription':list(qs.values()),'payments':list(payments.values()[:257])}
        if len(result['payments'])>256:raise ValueError('dependency_limit')
        import hashlib,json
        return hashlib.sha256(json.dumps(result,sort_keys=True,default=str).encode()).hexdigest()

INTERNAL={
 'finance.income.record':InternalRecord(NonVideoIncome,NonVideoIncomeForm,('category','description','amount','date'),'internal_income',mode='create',actor_field='created_by_id'),
 'finance.expense.record':InternalRecord(Expense,ExpenseForm,('category','description','amount','date'),'internal_non_salary_expense',mode='create',actor_field='created_by_id'),
 'finance.performance.payment.record':InternalRecord(PerformanceSubscriptionPayment,PerformanceSubscriptionPaymentForm,('amount','payment_date','payment_method','reference','notes'),'internal_performance_payment',mode='create',actor_field='created_by_id'),
}
