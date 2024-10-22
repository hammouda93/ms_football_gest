from django import forms
from .models import Video, Player, VideoEditor, Payment,Invoice, Expense
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.core.exceptions import ValidationError
from django.utils import timezone


class PlayerForm(forms.ModelForm):
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%Y/%m-%d','%m/%d/%Y','%m/%d/%y', '%d/%m/%Y'],  # Format pour l'entrée
        required=False,
    )
    class Meta:
        model = Player
        fields = ['name','date_of_birth','league', 'club','whatsapp_number']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['club'].widget.attrs['placeholder'] = "Entrez le club du joueur"
        self.fields['whatsapp_number'].widget.attrs['placeholder'] = "Numéro WhatsApp (+999999999999 ou 999999999)"
        
        # Pour le champ de la ligue
        self.fields['league'].widget.attrs['placeholder'] = "Sélectionnez la ligue"

class VideoForm(forms.ModelForm):
    
    SEASONS = [
        ('2022/2023', '2022/2023'),
        ('2023/2024', '2023/2024'),
        ('2024/2025', '2024/2025'),  # Default value
        ('2025/2026', '2025/2026'),
    ]

    season = forms.ChoiceField(choices=SEASONS, initial='2024/2025')

    deadline = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%Y/%m-%d','%m/%d/%Y','%m/%d/%y', '%d/%m/%Y'],  # Format pour l'entrée
        required=False,
    )
    class Meta:
        model = Video
        fields = ['status', 'advance_payment', 'total_payment', 'deadline', 'video_link','info', 'season']
    
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
        fields = ['payment_type', 'amount', 'payment_method']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount'].widget.attrs['placeholder'] = "Montant du paiement"
        self.fields['payment_type'].widget.attrs['placeholder'] = "Type de paiement"

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['video', 'total_amount', 'payment_method']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.add_input(Submit('submit', 'Créer la Facture'))


class ExpenseForm(forms.ModelForm):
    date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        input_formats=['%Y-%m-%d', '%Y/%m-%d','%m/%d/%Y','%m/%d/%y', '%d/%m/%Y'],  # Format pour l'entrée
        required=False,
    )
    video = forms.ModelChoiceField(queryset=Video.objects.none(), required=False)
    class Meta:
        model = Expense
        fields = ['amount', 'date', 'category','description', 'video']  # Ajout de category
        salary_amount = forms.DecimalField(required=False, decimal_places=2, max_digits=10)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['amount'].widget.attrs['placeholder'] = "Montant"
        self.fields['description'].widget.attrs['placeholder'] = "Description"
        if user and hasattr(user, 'videoeditor'):
            self.fields['video'].queryset = Video.objects.filter(editor=user.videoeditor)

        