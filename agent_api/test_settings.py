from ms_football_gest.settings import *  # noqa: F403

# Test databases are isolated from both the local working DB and Heroku.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
CELERY_TASK_ALWAYS_EAGER = False
DEBUG = False
