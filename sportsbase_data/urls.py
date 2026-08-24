from django.urls import path

from . import views


app_name = "performance"

urlpatterns = [
    path(
        "gestion/performances/",
        views.subscription_management,
        name="management",
    ),
    path(
        "gestion/performances/ajouter/",
        views.subscription_form,
        name="subscription_create",
    ),
    path(
        "gestion/performances/<int:pk>/modifier/",
        views.subscription_form,
        name="subscription_edit",
    ),
    path(
        "gestion/performances/<int:pk>/statut/",
        views.subscription_toggle,
        name="subscription_toggle",
    ),
    path(
        "gestion/performances/<int:pk>/synchroniser/",
        views.subscription_sync,
        name="subscription_sync",
    ),
    path(
        "portal/performance/",
        views.portal_performance_overview,
        name="portal_overview",
    ),
    path(
        "portal/performance/<int:player_id>/",
        views.portal_performance_detail,
        name="portal_detail",
    ),
    path(
        "portal/performance/<int:player_id>/match/<int:match_id>/",
        views.portal_match_detail,
        name="portal_match",
    ),
    path(
        "portal/performance/<int:player_id>/carte/<str:map_kind>/",
        views.portal_season_map,
        name="portal_season_map",
    ),
    path(
        "portal/performance/<int:player_id>/match/<int:match_id>/carte/<str:map_kind>/",
        views.portal_match_map,
        name="portal_match_map",
    ),
    path(
        "sportsbase/automation/jobs/next/",
        views.api_next_job,
        name="api_next_job",
    ),
    path(
        "sportsbase/automation/jobs/<int:job_id>/result/",
        views.api_job_result,
        name="api_job_result",
    ),
]
