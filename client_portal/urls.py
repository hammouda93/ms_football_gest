from django.urls import path

from . import views


app_name = "portal"

urlpatterns = [
    path("production/", views.production_board, name="production_board"),
    path("production/brief/", views.operations_brief, name="operations_brief"),
    path(
        "production/video/<int:video_id>/",
        views.production_video_detail,
        name="production_video",
    ),
    path(
        "production/video/<int:video_id>/workflow/",
        views.production_workflow_update,
        name="production_workflow_update",
    ),
    path(
        "production/video/<int:video_id>/activity/",
        views.production_activity_add,
        name="production_activity_add",
    ),
    path(
        "production/video/<int:video_id>/version/",
        views.production_version_add,
        name="production_version_add",
    ),
    path(
        "production/revision/<int:revision_id>/resolve/",
        views.production_revision_resolve,
        name="production_revision_resolve",
    ),
    path(
        "production/video/<int:video_id>/payment-request/",
        views.production_payment_request_add,
        name="production_payment_request_add",
    ),
    path(
        "production/video/<int:video_id>/whatsapp/<str:action>/",
        views.production_whatsapp,
        name="production_whatsapp",
    ),
    path("portal/login/", views.portal_login, name="login"),
    path("portal/logout/", views.portal_logout, name="logout"),
    path("portal/access/<str:token>/", views.portal_magic_access, name="magic_access"),
    path("portal/", views.portal_dashboard, name="dashboard"),
    path(
        "portal/player/<int:player_id>/",
        views.portal_player_detail,
        name="player",
    ),
    path("portal/video/<int:video_id>/", views.portal_video_detail, name="video"),
    path(
        "portal/video/<int:video_id>/media/",
        views.portal_media_submit,
        name="media_submit",
    ),
    path(
        "portal/version/<int:version_id>/revision/",
        views.portal_revision_request,
        name="revision_request",
    ),
    path(
        "portal/version/<int:version_id>/approve/",
        views.portal_version_approve,
        name="version_approve",
    ),
    path(
        "portal/payment/<int:payment_request_id>/open/",
        views.portal_payment_open,
        name="payment_open",
    ),
    path(
        "portal/agent/player-request/",
        views.portal_agent_player_request,
        name="agent_player_request",
    ),
    path("gestion/portail/", views.portal_management, name="management"),
    path(
        "gestion/portail/organisation/ajouter/",
        views.organization_create,
        name="organization_create",
    ),
    path(
        "gestion/portail/organisation/<int:pk>/",
        views.organization_detail,
        name="organization_detail",
    ),
    path(
        "gestion/portail/organisation/<int:pk>/joueur/ajouter/",
        views.organization_player_add,
        name="organization_player_add",
    ),
    path(
        "gestion/portail/organisation/<int:pk>/joueur/<int:link_id>/retirer/",
        views.organization_player_remove,
        name="organization_player_remove",
    ),
    path(
        "gestion/portail/compte/ajouter/",
        views.portal_account_create,
        name="account_create",
    ),
    path(
        "gestion/portail/compte/<int:profile_id>/lien/",
        views.portal_access_link_generate,
        name="access_link_generate",
    ),
    path(
        "gestion/portail/demande-joueur/<int:request_id>/",
        views.agent_player_request_review,
        name="agent_request_review",
    ),
    path("portal/manifest.webmanifest", views.portal_manifest, name="manifest"),
    path("portal/service-worker.js", views.portal_service_worker, name="service_worker"),
]
