"""Authenticated encryption for recoverable portal bearer tokens."""
import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class PortalTokenEncryptionError(RuntimeError):
    pass


def _cipher():
    # Optional dedicated key. Fallback is domain-separated from Django's
    # signing key, so existing deployments do not require a config change.
    configured = os.environ.get("PORTAL_ACCESS_ENCRYPTION_KEY", "").strip()
    keys = []
    try:
        if configured:
            keys.append(Fernet(configured.encode("ascii")))
        for secret in [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]:
            derived = hmac.new(
                secret.encode("utf-8"), b"msfootball:portal-access:v1", hashlib.sha256
            ).digest()
            keys.append(Fernet(base64.urlsafe_b64encode(derived)))
        return MultiFernet(keys)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise PortalTokenEncryptionError("Configuration de chiffrement du portail invalide.") from exc


def encrypt_token(raw_token):
    return _cipher().encrypt(raw_token.encode("ascii")).decode("ascii")


def decrypt_token(encrypted_token):
    try:
        return _cipher().decrypt(encrypted_token.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise PortalTokenEncryptionError(
            "Le lien enregistré ne peut pas être déchiffré. Vérifiez la clé de chiffrement."
        ) from exc
