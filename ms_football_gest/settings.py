"""
Django settings for ms_football_gest project.

Generated by 'django-admin startproject' using Django 5.1.2.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.1/ref/settings/
"""

from pathlib import Path
import os
from celery.schedules import crontab


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-kx5#*2*9l*64p#o^&zk!++t0m&_(1&bi@+kur$up%=#*ra9m^^'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['msfootball-1a882b44ed52.herokuapp.com', 'localhost', '127.0.0.1']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'gestion_joueurs',
    'crispy_forms',
    'crispy_bootstrap4',
]

ASGI_APPLICATION = 'MS_FOOTBALL_GEST.asgi.application'

# Configure your channel layers (using in-memory as an example)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'gestion_joueurs.middleware.CurrentUserMiddleware',
]

ROOT_URLCONF = 'ms_football_gest.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'gestion_joueurs.context_processors.notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'ms_football_gest.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql', # on utilise l'adaptateur postgresql
        'NAME': 'gestion_ms', # le nom de notre base de donnees creee precedemment
        'USER': 'postgres', # attention : remplacez par votre nom d'utilisateur
        'PASSWORD': 'salih1',
        'HOST': '127.0.0.1',
        'PORT': '5432',
        'ATOMIC_REQUESTS': True,
        #'ENGINE': 'django.db.backends.sqlite3',
        #'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/
# For Heroku (or other production environments):
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'
# For development, ensure you have the following:
if DEBUG:
    STATICFILES_DIRS = [
        BASE_DIR / "gestion_joueurs/static",  # Adjust according to your project structure
    ]

# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'user_login'  # Nom de l'URL pour la page de connexion
LOGOUT_URL = 'user_logout'  # Nom de l'URL pour la page de déconnexion
LOGIN_REDIRECT_URL = 'dashboard'  # Où rediriger après la connexion
CRISPY_TEMPLATE_PACK = 'bootstrap4'

CELERY_BROKER_URL = 'redis://localhost:6380/0' 
CELERY_RESULT_BACKEND = 'redis://localhost:6380/0'
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_BEAT_SCHEDULE = {
    'notify-birthday-every-day': {
        'task': 'gestion_joueurs.tasks.notify_birthday',
        'schedule': crontab('*/3'),  # Every day at midnight minute=0, hour=0
    },
    'notify_pending_videos': {
        'task': 'gestion_joueurs.tasks.notify_pending_videos',
        'schedule': crontab(minute='*/3'),  # Every 30 minutes
    },
    'notify_in_progress_or_completed_collab_videos': {
        'task': 'gestion_joueurs.tasks.notify_in_progress_or_completed_collab_videos',
        'schedule': crontab(minute='*/3'),  # Every 30 minutes
    },
    'notify_past_deadline_status_videos': {
        'task': 'gestion_joueurs.tasks.notify_past_deadline_status_videos',
        'schedule': crontab(minute='*/3'),  # Every hour
    },
    'check_video_count': {
        'task': 'gestion_joueurs.tasks.check_video_count',
        'schedule': crontab(minute='*/3'),  # Every hour
    },
    'notify_salary_due_for_delivered_videos': {
        'task': 'gestion_joueurs.tasks.notify_salary_due_for_delivered_videos',
        'schedule': crontab(minute='*/3'),  # Every hour
    },
    'generate_first_day_of_current_month_report': {
        'task': 'gestion_joueurs.tasks.generate_first_day_of_current_month_report',
        'schedule': crontab(minute='*/3'),  # Every 1st day of the month at midnight
    },
}

""" CELERY_BEAT_SCHEDULE = {
    'notify-birthday-every-day': {
        'task': 'gestion_joueurs.tasks.notify_birthday',
        'schedule': crontab(minute=0, hour=0),  # Every day at midnight
    },
    'notify-pending-videos-every-30-minutes': {
        'task': 'gestion_joueurs.tasks.notify_pending_videos',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
    'notify-in-progress-videos-every-30-minutes': {
        'task': 'gestion_joueurs.tasks.notify_in_progress_videos',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
    'notify_salary_due_for_delivered_videos': {
        'task': 'gestion_joueurs.tasks.notify_salary_due_for_delivered_videos,
        'schedule': crontab(minute='*/3'),  # Every hour
    },
    'check_video_count': {
        'task': 'gestion_joueurs.tasks.check_video_count',
        'schedule': crontab(minute='*/3'),  # Every hour
    },
    'check-delivered-videos-every-hour': {
        'task': 'gestion_joueurs.tasks.check_delivered_videos',
        'schedule': crontab(minute=0, hour='*'),  # Every hour
    },
    'check-completed-videos-every-hour': {
        'task': 'gestion_joueurs.tasks.check_completed_videos',
        'schedule': crontab(minute=0, hour='*'),  # Every hour
    },
    'check-salary-after-deadline-every-hour': {
        'task': 'gestion_joueurs.tasks.check_salary_after_deadline',
        'schedule': crontab(minute=0, hour='*'),  # Every hour
    },
} """





""" CELERY_IMPORTS = ('gestion_joueurs.tasks',)
CELERY_BEAT_SCHEDULE = {
    'send-reminders-every-day': {
        'task': 'gestion_joueurs.tasks.send_reminders',
        'schedule': crontab(hour=8, minute=0),  # Runs every day at 8 AM
    },
} """