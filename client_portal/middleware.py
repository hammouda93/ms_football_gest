from django.contrib.auth import logout
from django.shortcuts import redirect

from .models import PortalAccessLink


class PortalAreaIsolationMiddleware:
    """Keep external portal accounts outside internal management pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        link_id = request.session.get("portal_access_link_id")
        if user.is_authenticated and link_id and request.path.startswith("/portal/"):
            link = PortalAccessLink.objects.select_related("user", "user__portal_profile").filter(
                pk=link_id, user_id=user.pk,
            ).first()
            if not link or not link.is_usable:
                logout(request)
                user = request.user
        internal_auth_paths = {
            "/gestion_joueurs/login/",
            "/gestion_joueurs/logout/",
        }
        if (
            user.is_authenticated
            and request.path.startswith("/gestion_joueurs/")
            and request.path not in internal_auth_paths
            and not user.is_staff
            and not user.is_superuser
            and not hasattr(user, "videoeditor")
            and hasattr(user, "portal_profile")
        ):
            return redirect("portal:dashboard")
        response = self.get_response(request)
        if request.path.startswith("/portal/"):
            response["Cache-Control"] = "no-store, private"
            response["Pragma"] = "no-cache"
            # YouTube embeds require an origin identity (otherwise player error 153).
            # This policy sends only the site origin cross-domain, never the portal path
            # or a reusable access token.
            if not response.has_header("Referrer-Policy"):
                response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
