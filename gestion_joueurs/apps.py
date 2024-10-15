from django.apps import AppConfig


class GestionJoueursConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gestion_joueurs'

    def ready(self):
        import gestion_joueurs.signals  # Ensure your signals are imported