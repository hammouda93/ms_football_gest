from functools import wraps
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def production_required(view_func):
    @login_required(login_url="user_login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.user.is_superuser or hasattr(request.user, "videoeditor"):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied

    return wrapped


def _portal_profile_for_request(user):
    try:
        profile = user.portal_profile
    except Exception:
        profile = None
    if profile is not None:
        return profile
    if user.is_superuser:
        return SimpleNamespace(
            display_name=user.get_full_name().strip() or user.get_username(),
            preferred_language="fr",
            is_active=True,
        )
    return None


def portal_required(view_func):
    @login_required(login_url="portal:login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        profile = _portal_profile_for_request(request.user)
        if profile is None or (
            not request.user.is_superuser and not profile.is_active
        ):
            raise PermissionDenied
        request.portal_profile = profile
        request.portal_overview_admin = request.user.is_superuser
        return view_func(request, *args, **kwargs)

    return wrapped


def portal_admin_required(view_func):
    @login_required(login_url="user_login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped
