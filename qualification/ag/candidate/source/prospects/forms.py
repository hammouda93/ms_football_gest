import re
from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .models import Prospect
from .services import validate_transfermarkt_profile_url


class ProspectRequestForm(forms.ModelForm):
    class Meta:
        model = Prospect
        fields = (
            "transfermarkt_url",
            "full_name",
            "date_of_birth",
            "whatsapp_number",
            "email",
            "country",
            "club",
            "league",
            "position",
            "season",
            "service_type",
            "match_links",
            "desired_deadline",
            "message",
        )
        widgets = {
            "transfermarkt_url": forms.URLInput(
                attrs={
                    "autocomplete": "url",
                    "placeholder": "Collez le lien Transfermarkt du joueur",
                }
            ),
            "full_name": forms.TextInput(
                attrs={"autocomplete": "name", "placeholder": "Nom et prénom"}
            ),
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
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
                        "https://...\nAjoutez un lien par ligne "
                        "(facultatif avec Transfermarkt)"
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
            "transfermarkt_url": (
                "Facultatif. Utilisez le bouton Importer pour préremplir les données."
            ),
            "date_of_birth": "Facultatif si aucune date n’est disponible.",
            "whatsapp_number": "Incluez l’indicatif du pays pour que nous puissions vous répondre.",
            "email": "Facultatif.",
            "country": "Facultatif.",
            "club": "Facultatif si vous êtes actuellement sans club.",
            "match_links": (
                "Facultatif avec un profil Transfermarkt. Sinon, ajoutez au "
                "moins un lien HTTP ou HTTPS."
            ),
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

    def clean_transfermarkt_url(self):
        return validate_transfermarkt_profile_url(
            self.cleaned_data.get("transfermarkt_url", "")
        )

    def clean_match_links(self):
        raw_links = self.cleaned_data.get("match_links", "")
        links = [line.strip() for line in raw_links.splitlines() if line.strip()]
        validator = URLValidator(schemes=("http", "https"))

        if not links:
            if self.cleaned_data.get("transfermarkt_url"):
                return ""
            raise ValidationError(
                "Ajoutez au moins un lien de match ou un lien Transfermarkt."
            )

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


class ProspectManagementForm(ProspectRequestForm):
    class Meta(ProspectRequestForm.Meta):
        fields = ProspectRequestForm.Meta.fields + (
            "status",
            "internal_notes",
        )
        widgets = {
            **ProspectRequestForm.Meta.widgets,
            "internal_notes": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Notes visibles uniquement par l’équipe MS Football",
                }
            ),
        }
        help_texts = {
            **ProspectRequestForm.Meta.help_texts,
            "internal_notes": "Ces notes ne sont jamais affichées au prospect.",
        }
