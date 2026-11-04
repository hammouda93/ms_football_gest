from django.urls import path
from . import views

urlpatterns = [path('schema/', views.schema), path('query/', views.query)]
