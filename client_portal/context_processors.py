from .portal_i18n import get_portal_copy, normalize_portal_language


def portal_language(request):
    """Expose one coherent language/copy catalog to every portal template."""
    if not getattr(request, "path", "").startswith("/portal/"):
        return {"portal_language": "fr", "pc": get_portal_copy("fr")}
    profile = getattr(request, "portal_profile", None)
    if profile is None and getattr(request, "user", None) is not None:
        try:
            profile = request.user.portal_profile
        except Exception:
            profile = None
    language = normalize_portal_language(
        getattr(profile, "preferred_language", "fr")
    )
    return {
        "portal_language": language,
        "pc": get_portal_copy(language),
    }
