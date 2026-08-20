from django import forms
from django.contrib.auth.forms import AuthenticationForm

from gestion_joueurs.models import Player
from prospects.services import validate_transfermarkt_profile_url

from .models import (
    AgentPlayerRequest,
    MediaSubmission,
    Organization,
    OrganizationMembership,
    PaymentRequest,
    PortalProfile,
    RevisionRequest,
    VideoActivity,
    VideoVersion,
    VideoWorkflow,
)


def _style_fields(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.CheckboxInput):
            css_class = "form-check-input"
        elif isinstance(widget, forms.Select):
            css_class = "form-control"
        else:
            css_class = "form-control"
        widget.attrs["class"] = " ".join(
            part for part in (widget.attrs.get("class", ""), css_class) if part
        )


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


class PortalLoginForm(AuthenticationForm):
    username = forms.CharField(label="Identifiant ou e-mail")
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


class OrganizationForm(StyledModelForm):
    class Meta:
        model = Organization
        fields = (
            "name",
            "kind",
            "contact_name",
            "email",
            "whatsapp_number",
            "country",
            "is_active",
        )


class PortalAccountForm(forms.Form):
    account_type = forms.ChoiceField(
        label="Type de compte",
        choices=PortalProfile.AccountType.choices,
    )
    display_name = forms.CharField(label="Nom affiché", max_length=160)
    email = forms.EmailField(label="E-mail")
    whatsapp_number = forms.CharField(label="WhatsApp", max_length=24, required=False)
    preferred_language = forms.ChoiceField(
        label="Langue",
        choices=(("fr", "Français"), ("en", "English"), ("ar", "العربية")),
    )
    player = forms.ModelChoiceField(
        label="Joueur existant",
        queryset=Player.objects.none(),
        required=False,
        help_text="Le compte joueur sera lié sans modifier sa fiche.",
    )
    organization = forms.ModelChoiceField(
        label="Organisation",
        queryset=Organization.objects.none(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["player"].queryset = Player.objects.order_by("name", "club")
        self.fields["organization"].queryset = Organization.objects.filter(
            is_active=True
        ).order_by("name")
        _style_fields(self)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if PortalProfile.objects.filter(user__email__iexact=email).exists():
            raise forms.ValidationError("Un compte portail utilise déjà cet e-mail.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        account_type = cleaned_data.get("account_type")
        player = cleaned_data.get("player")
        organization = cleaned_data.get("organization")

        if account_type == PortalProfile.AccountType.PLAYER and not player:
            self.add_error("player", "Sélectionnez le joueur associé à ce compte.")
        if account_type in {
            PortalProfile.AccountType.AGENT,
            PortalProfile.AccountType.ACADEMY,
        } and not organization:
            self.add_error("organization", "Sélectionnez l’organisation associée.")
        return cleaned_data


class OrganizationPlayerForm(forms.Form):
    player = forms.ModelChoiceField(
        label="Joueur existant",
        queryset=Player.objects.none(),
    )
    label = forms.CharField(label="Référence interne", max_length=100, required=False)

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Player.objects.order_by("name", "club")
        if organization:
            queryset = queryset.exclude(
                portal_organization_links__organization=organization,
                portal_organization_links__is_active=True,
            )
        self.fields["player"].queryset = queryset
        _style_fields(self)


class VideoWorkflowForm(StyledModelForm):
    class Meta:
        model = VideoWorkflow
        fields = ("stage", "priority", "progress", "next_action", "blocked_reason")
        widgets = {
            "blocked_reason": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("stage") == VideoWorkflow.Stage.BLOCKED
            and not cleaned_data.get("blocked_reason", "").strip()
        ):
            self.add_error(
                "blocked_reason",
                "Indiquez pourquoi la production est bloquée.",
            )
        return cleaned_data


class VideoActivityForm(StyledModelForm):
    class Meta:
        model = VideoActivity
        fields = ("message", "visibility")
        widgets = {"message": forms.Textarea(attrs={"rows": 3})}


class MediaSubmissionForm(StyledModelForm):
    class Meta:
        model = MediaSubmission
        fields = ("category", "title", "source_url", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class VideoVersionForm(StyledModelForm):
    class Meta:
        model = VideoVersion
        fields = ("title", "preview_url", "final_url", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class RevisionRequestForm(forms.Form):
    timecode = forms.CharField(
        label="Moment dans la vidéo",
        max_length=8,
        required=False,
        help_text="Format mm:ss, par exemple 02:35.",
    )
    comment = forms.CharField(
        label="Correction demandée",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)

    def clean_timecode(self):
        value = self.cleaned_data.get("timecode", "").strip()
        if not value:
            return None
        parts = value.split(":")
        if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
            raise forms.ValidationError("Utilisez le format mm:ss ou hh:mm:ss.")
        numbers = [int(part) for part in parts]
        if any(number < 0 for number in numbers) or numbers[-1] >= 60:
            raise forms.ValidationError("Le timecode n’est pas valide.")
        if len(numbers) == 2:
            minutes, seconds = numbers
            return minutes * 60 + seconds
        hours, minutes, seconds = numbers
        if minutes >= 60:
            raise forms.ValidationError("Le timecode n’est pas valide.")
        return hours * 3600 + minutes * 60 + seconds


class RevisionResolutionForm(forms.Form):
    status = forms.ChoiceField(
        label="Statut",
        choices=(
            (RevisionRequest.Status.IN_PROGRESS, "En cours"),
            (RevisionRequest.Status.RESOLVED, "Résolue"),
            (RevisionRequest.Status.REJECTED, "Non retenue"),
        ),
    )
    staff_response = forms.CharField(
        label="Réponse au client",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_fields(self)


class PaymentRequestForm(StyledModelForm):
    class Meta:
        model = PaymentRequest
        fields = ("label", "amount", "due_date", "payment_url")
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}


class AgentPlayerRequestForm(StyledModelForm):
    class Meta:
        model = AgentPlayerRequest
        fields = (
            "organization",
            "full_name",
            "transfermarkt_url",
            "club",
            "whatsapp_number",
            "notes",
        )
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        organizations = Organization.objects.none()
        if user and user.is_authenticated:
            organizations = Organization.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                memberships__role__in={
                    OrganizationMembership.Role.OWNER,
                    OrganizationMembership.Role.STAFF,
                },
                is_active=True,
            ).distinct()
        self.fields["organization"].queryset = organizations

    def clean_transfermarkt_url(self):
        return validate_transfermarkt_profile_url(
            self.cleaned_data.get("transfermarkt_url", "")
        )
