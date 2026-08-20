from django.urls import path

from . import views


app_name = "prospects"

urlpatterns = [
    path("demande-video/", views.request_create, name="request_create"),
    path("demande-video/merci/", views.request_success, name="request_success"),
    path("gestion/prospects/", views.prospect_list, name="prospect_list"),
    path(
        "gestion/prospects/<int:pk>/statut/",
        views.prospect_status_update,
        name="prospect_status_update",
    ),
]
