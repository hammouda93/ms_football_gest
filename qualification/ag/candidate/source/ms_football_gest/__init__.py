from .celery import app as celery_app
default_app_config = 'gestion_joueurs.apps.GestionJoueursConfig'
__all__ = ('celery_app',)
