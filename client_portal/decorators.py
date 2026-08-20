from functools import wraps

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


def portal_required(view_func):
    @login_required(login_url="portal:login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        try:
            profile = request.user.portal_profile
        except Exception as exc:
            raise PermissionDenied from exc
        if not profile.is_active:
            raise PermissionDenied
        request.portal_profile = profile
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
