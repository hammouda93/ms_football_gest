import re
from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .models import Prospect


class ProspectRequestForm(forms.ModelForm):
    class Meta:
        model = Prospect
        fields = (
            "full_name",
            "whatsapp_number",
            "email",
            "country",
            "club",
            "position",
            "season",
            "service_type",
            "match_links",
            "desired_deadline",
            "message",
        )
        widgets = {
            "full_name": forms.TextInput(
                attrs={"autocomplete": "name", "placeholder": "Nom et prénom"}
            ),
            "whatsapp_number": forms.TextInput(
                attrs={
                    "autocomplete": "tel",
                    "inputmode": "tel",
                    "placeholder": "+216 20 123 456",
                }
            ),
            "email": forms.EmailInput(
                attrs={"autocomplete": "email", "placeholder": "nom@exemple.com"}
            ),
            "country": forms.TextInput(
                attrs={"autocomplete": "country-name", "placeholder": "Tunisie"}
            ),
            "club": forms.TextInput(attrs={"placeholder": "Club actuel (facultatif)"}),
            "season": forms.TextInput(attrs={"placeholder": "2025/2026"}),
            "match_links": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": (
                        "https://...\nAjoutez un lien par ligne (YouTube, Drive, etc.)"
                    ),
                }
            ),
            "desired_deadline": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Objectif, style souhaité ou autre précision...",
                }
            ),
        }
        help_texts = {
            "whatsapp_number": "Incluez l’indicatif du pays pour que nous puissions vous répondre.",
            "email": "Facultatif.",
            "club": "Facultatif si vous êtes actuellement sans club.",
            "match_links": "Un lien HTTP ou HTTPS par ligne.",
            "desired_deadline": "Facultatif.",
            "message": "Facultatif.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_whatsapp_number(self):
        raw_number = self.cleaned_data["whatsapp_number"].strip()
        has_plus_prefix = raw_number.startswith("+")
        digits = re.sub(r"\D", "", raw_number)
        normalized = f"+{digits}" if has_plus_prefix else digits

        # Model validators run after clean_<field>(); this makes spaces and dashes
        # convenient for mobile users while keeping a predictable stored value.
        return normalized

    def clean_match_links(self):
        raw_links = self.cleaned_data["match_links"]
        links = [line.strip() for line in raw_links.splitlines() if line.strip()]
        validator = URLValidator(schemes=("http", "https"))

        if not links:
            raise ValidationError("Ajoutez au moins un lien de match.")

        invalid_links = []
        for link in links:
            try:
                validator(link)
            except ValidationError:
                invalid_links.append(link)

        if invalid_links:
            raise ValidationError(
                "Chaque ligne doit contenir un lien HTTP ou HTTPS valide."
            )

        return "\n".join(links)

    def clean_desired_deadline(self):
        deadline = self.cleaned_data.get("desired_deadline")
        if deadline and deadline < date.today():
            raise ValidationError("La date souhaitée ne peut pas être passée.")
        return deadline


class ProspectStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Prospect.Status.choices)
