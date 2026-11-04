from django.urls import path

from . import views


app_name = "agent"
urlpatterns = [
    path("catalog/", views.catalog, name="catalog"),
    path("describe/", views.describe, name="describe"),
    path("query/", views.query, name="query"),
    path("actions/describe/", views.action_describe, name="action_describe"),
    path("actions/prepare/", views.action_prepare, name="action_prepare"),
    path("actions/confirm/", views.action_confirm, name="action_confirm"),
    path("actions/receipt/", views.action_receipt, name="action_receipt"),
]
