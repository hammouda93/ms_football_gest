"""Fast, deterministic settings for the repository test suite."""

from .settings import *  # noqa: F401,F403


DEBUG = False
try:
    del STATICFILES_STORAGE  # noqa: F405
except NameError:
    pass
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_repository.sqlite3",  # noqa: F405
    },
}
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
