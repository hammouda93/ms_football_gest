from django.shortcuts import redirect


class PortalAreaIsolationMiddleware:
    """Keep external portal accounts outside internal management pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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
            response["Referrer-Policy"] = "no-referrer"
        return response
