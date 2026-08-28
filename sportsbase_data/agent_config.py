"""Dependency-free configuration helpers for the local Performance agent."""

import os


def _enabled(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "oui"}


def youtube_upload_enabled():
    """Let subscriptions drive YouTube unless a local kill switch is explicit."""
    value = os.getenv("YOUTUBE_UPLOAD_ENABLED")
    if value is None or not value.strip():
        return True
    return _enabled("YOUTUBE_UPLOAD_ENABLED", True)
