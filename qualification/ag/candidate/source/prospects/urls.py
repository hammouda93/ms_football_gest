from django.urls import path

from . import views


app_name = "prospects"

urlpatterns = [
    path("demande-video/", views.request_create, name="request_create"),
    path("demande-video/merci/", views.request_success, name="request_success"),
    path(
        "demande-video/importer-transfermarkt/",
        views.transfermarkt_import_preview,
        name="transfermarkt_import",
    ),
    path("gestion/prospects/", views.prospect_list, name="prospect_list"),
    path(
        "gestion/prospects/<int:pk>/modifier/",
        views.prospect_edit,
        name="prospect_edit",
    ),
    path(
        "gestion/prospects/<int:pk>/supprimer/",
        views.prospect_delete,
        name="prospect_delete",
    ),
    path(
        "gestion/prospects/<int:pk>/convertir/",
        views.prospect_convert,
        name="prospect_convert",
    ),
    path(
        "gestion/prospects/<int:pk>/whatsapp/",
        views.prospect_whatsapp_start,
        name="prospect_whatsapp_start",
    ),
    path(
        "gestion/prospects/<int:pk>/statut/",
        views.prospect_status_update,
        name="prospect_status_update",
    ),
]
