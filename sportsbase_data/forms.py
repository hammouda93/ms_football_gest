from django import forms

from gestion_joueurs.models import Player

from .models import (
    PerformanceReport,
    PerformanceSubscriptionPayment,
    SportsBaseSubscription,
)


class SportsBaseSubscriptionForm(forms.ModelForm):
    class Meta:
        model = SportsBaseSubscription
        fields = (
            "player",
            "season",
            "starts_on",
            "ends_on",
            "sync_from_date",
            "first_match_id",
            "all_actions_enabled",
            "email_delivery_enabled",
            "youtube_delivery_enabled",
            "report_language",
            "total_amount",
            "currency",
            "payment_url",
            "sync_interval_hours",
            "is_active",
        )
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
            "sync_from_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Player.objects.order_by("name", "club")
        if self.instance and self.instance.pk:
            queryset = queryset.filter(
                sportsbase_subscription__isnull=True
            ) | Player.objects.filter(pk=self.instance.player_id)
        else:
            queryset = queryset.filter(sportsbase_subscription__isnull=True)
        self.fields["player"].queryset = queryset.distinct().order_by("name", "club")
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"
        self.fields["player"].widget.attrs["class"] += " searchable-player-select"

    def clean(self):
        cleaned = super().clean()
        player = cleaned.get("player")
        if cleaned.get("is_active") and player and not player.sportsbase_url:
            self.add_error(
                "player",
                "Ajoutez d’abord le lien SportsBase dans la fiche de ce joueur.",
            )
        return cleaned


class PerformanceSubscriptionPaymentForm(forms.ModelForm):
    class Meta:
        model = PerformanceSubscriptionPayment
        fields = ("amount", "payment_date", "payment_method", "reference", "notes")
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, subscription=None, **kwargs):
        self.subscription = subscription
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if (
            self.subscription
            and self.subscription.total_amount > 0
            and amount > self.subscription.remaining_balance
        ):
            raise forms.ValidationError(
                f"Le montant dépasse le solde restant de "
                f"{self.subscription.remaining_balance:.2f} {self.subscription.currency}."
            )
        return amount


class PerformanceReportForm(forms.ModelForm):
    class Meta:
        model = PerformanceReport
        fields = (
            "status",
            "title",
            "executive_summary",
            "strengths",
            "improvement_areas",
            "analyst_notes",
        )
        widgets = {
            "executive_summary": forms.Textarea(attrs={"rows": 5}),
            "strengths": forms.Textarea(attrs={"rows": 6}),
            "improvement_areas": forms.Textarea(attrs={"rows": 6}),
            "analyst_notes": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
