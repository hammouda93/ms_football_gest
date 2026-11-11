"""Exact internal branch of record_payment, using its real form and view."""
from decimal import Decimal
from django.contrib.auth.models import User
from django.contrib.messages.storage.cookie import CookieStorage
from django.test import RequestFactory
from gestion_joueurs.models import Payment,Invoice,Video
from gestion_joueurs.forms import PaymentForm
from gestion_joueurs.views import record_payment
from .internal import InternalRecord
from .declarative import scalar
import hashlib,json

class HighlightPayment(InternalRecord):
    def contract(self):
        c=super().contract();c['fields'].append('video');c['required'].append('video');c['schema']['video']={'type':'integer'}
        # The application derives partial/final from the *resulting balance*.
        # Keep payment_type as an accepted legacy field, not a required input.
        c['required'].remove('payment_type')
        c['schema']['payment_type']['derivedFrom']='invoice_balance_after_payment'
        c['schema']['payment_type']['optionalInput']=True
        c['sourceView']='gestion_joueurs.views.record_payment';c['preconditions']=['existing_invoice','positive_amount_not_exceeding_balance','single_step'];c['effects']=['payment','invoice_amount_paid_and_status']
        c['inputExample']={'video':1980,'amount':'150.00','payment_method':'bank_transfer'}
        c['currency']='TND'
        c['paymentTypePolicy']='optional input accepted for compatibility; persisted type always calculated from remaining invoice balance'
        return c
    def cleaned(self,values,actor_id,lock=False):
        if set(values)-{'video','amount','payment_method','payment_type'} or not {'video','amount','payment_method'}<=set(values):
            raise ValueError('field_forbidden')
        # The form still validates any explicitly supplied historical type;
        # when Hermes omits it, supply the internal form with a valid placeholder.
        form_values=dict(values)
        form_values.setdefault('payment_type','partial')
        obj,changes=super().cleaned(form_values,actor_id,lock)
        qs=Invoice.objects.select_for_update() if lock else Invoice.objects
        try:
            invoice=qs.get(video_id=values['video'])
            video=Video.objects.get(pk=values['video'])
        except (Invoice.DoesNotExist,Video.DoesNotExist):
            raise ValueError('invoice_or_video_missing') from None
        amount=changes['amount'];paid=invoice.amount_paid+amount
        if amount>invoice.total_amount-invoice.amount_paid:raise ValueError('overpayment')
        changes.update(video_id=video.pk,player_id=video.player_id,invoice_id=invoice.pk,remaining_balance=invoice.total_amount-paid,payment_type='partial' if paid<invoice.total_amount else 'final')
        return obj,changes
    def snapshot(self,values,actor_id,lock=False):
        self.cleaned(values,actor_id,lock)
        result={}
        for name,qs in [('invoice',Invoice.objects.filter(video_id=values['video'])),('video',Video.objects.filter(pk=values['video'])),('payments',Payment.objects.filter(video_id=values['video']).order_by('pk'))]:
            if lock:qs=qs.select_for_update()
            result[name]=list(qs.values()[:257])
            if len(result[name])>256:raise ValueError('dependency_limit')
        return hashlib.sha256(json.dumps(result,sort_keys=True,default=str).encode()).hexdigest()
    def preview(self,step,actor_id):
        x=super().preview(step,actor_id);invoice=Invoice.objects.get(video_id=step['values']['video'])
        paid=invoice.amount_paid+Decimal(step['values']['amount'])
        x['invoice']={'id':invoice.pk,'new':scalar({'amount_paid':paid,'status':'partially_paid' if paid<invoice.total_amount else 'paid'})}
        from .internal import financial_projection
        journal=list(Payment.objects.filter(video_id=step['values']['video']).order_by('pk').values('amount')[:257])
        if len(journal)>256:raise ValueError('dependency_limit')
        parent={'total_amount':invoice.total_amount,'amount_paid':invoice.amount_paid}
        x['financial']={'before':financial_projection('highlight',parent,journal),'after':financial_projection('highlight',parent,journal,Decimal(step['values']['amount']))}
        return x
    def apply(self,values,actor_id):
        _obj,clean=self.cleaned(values,actor_id,True)
        previous=set(Payment.objects.filter(video_id=values['video']).values_list('pk',flat=True))
        # Pass the derived type to the unchanged Django form, never require
        # Hermes to guess whether the payment will close the invoice.
        request=RequestFactory().post('/internal-registration/',{k:clean[k] for k in self.fields});request.user=User.objects.get(pk=actor_id);request._messages=CookieStorage(request)
        response=record_payment(request,values['video'])
        if response.status_code!=302:raise ValueError('payment_view_failed')
        return Payment.objects.get(video_id=values['video'],pk__in=Payment.objects.filter(video_id=values['video']).exclude(pk__in=previous).values_list('pk',flat=True))

HIGHLIGHT={'finance.highlight.payment.record':HighlightPayment(Payment,PaymentForm,('payment_type','amount','payment_method'),'internal_highlight_payment',mode='create',actor_field='created_by_id')}
