from django import forms
from .models import Video, Player
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = ['name', 'age', 'club', 'whatsapp_number']

class VideoForm(forms.ModelForm):
    deadline = forms.DateField(required=False, input_formats=['%Y-%m-%d', '%Y/%m-%d','%m/%d/%Y','%m/%d/%y', '%d/%m/%Y'])
    class Meta:
        model = Video
        fields = ['editor', 'status', 'advance_payment', 'total_payment', 'deadline', 'video_link']

class VideoEditorRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']