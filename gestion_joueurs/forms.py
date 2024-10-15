from django import forms
from .models import Video, Player, VideoEditor, Payment
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.core.exceptions import ValidationError
from django.utils import timezone


class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ['name', 'age','league', 'club','whatsapp_number']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['placeholder'] = "Entrez le nom du joueur"
        self.fields['club'].widget.attrs['placeholder'] = "Entrez le club du joueur"
        self.fields['age'].widget.attrs['placeholder'] = "Âge (doit être non-négatif)"
        self.fields['whatsapp_number'].widget.attrs['placeholder'] = "Numéro WhatsApp (+999999999999 ou 999999999)"
        
        # Pour le champ de la ligue
        self.fields['league'].widget.attrs['placeholder'] = "Sélectionnez la ligue"

class VideoForm(forms.ModelForm):
    
    deadline = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%Y/%m-%d','%m/%d/%Y','%m/%d/%y', '%d/%m/%Y'],  # Format pour l'entrée
        required=False,
    )
    class Meta:
        model = Video
        fields = ['status', 'advance_payment', 'total_payment', 'deadline', 'video_link','info']
    
    editor = forms.ModelChoiceField(queryset=VideoEditor.objects.all(), required=True)

    def __init__(self, *args, **kwargs):
        # Récupérer l'utilisateur connecté
        user = kwargs.pop('user', None)
        super(VideoForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'videoeditor'):
            # Définir l'éditeur par défaut sur l'utilisateur connecté
            self.fields['editor'].initial = user.videoeditor
    # Crispy Forms helper
        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Créer la Vidéo', css_class='btn btn-primary'))
    
    def clean(self):
        cleaned_data = super().clean()
        advance_payment = cleaned_data.get("advance_payment")
        total_payment = cleaned_data.get("total_payment")

        if advance_payment is not None and total_payment is not None:
            if advance_payment > total_payment:
                raise ValidationError("L'avance ne peut pas être supérieure au montant total.")

        return cleaned_data
    
    def clean_deadline(self):
        deadline = self.cleaned_data.get('deadline')
        if deadline and deadline < timezone.now().date():
            raise ValidationError("La date de deadline ne peut pas être dans le passé.")
        return deadline

class VideoEditorRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['player', 'video', 'amount', 'payment_type']