from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parent
SECRET_KEY='FICTION-extension-only'
INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','gestion_joueurs.apps.GestionJoueursConfig','client_portal.apps.ClientPortalConfig','sportsbase_data.apps.SportsbaseDataConfig','prospects.apps.ProspectsConfig','crispy_forms','crispy_bootstrap4','actions','data_access']
DATABASES={'default':{'ENGINE':'django.db.backends.postgresql','NAME':'msf_highlights_fiction','USER':'msf_highlights_fixture','HOST':'127.0.0.1','PORT':'55981','CONN_MAX_AGE':0}}
DATABASES['verification']=deepcopy(DATABASES['default'])
DATABASES['data_access']=deepcopy(DATABASES['default'])
USE_TZ=True
TIME_ZONE='Africa/Tunis'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
ROOT_URLCONF='urls_fixture'
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','actions.pilot.PrepareOnlyBoundary']
ACTIONS_ENABLED=False
ACTIONS_APPROVAL_KEY=''
ACTIONS_VERIFICATION_KEY='FICTION_extension_verify_000000000000000000'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','APP_DIRS':True}]
EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
STATIC_URL='/static/'
MEDIA_ROOT=ROOT/'evidence/media'
PUBLIC_SITE_URL='http://testserver'
GOOGLE_SHEETS_ENABLED=False
TELEGRAM_BOT_TOKEN=''
CELERY_BROKER_URL='memory://'
CELERY_BEAT_SCHEDULE={}
ALLOWED_HOSTS=['testserver']
