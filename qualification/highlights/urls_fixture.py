from django.urls import path,include
# The real writer boundary dispatches its exact namespace before URL resolution.
urlpatterns=[path('data/v1/',include('data_access.urls'))]
urlpatterns.append(path('fixture-dashboard/',lambda r: None,name='dashboard'))
urlpatterns.append(path('fixture-payments/',lambda r: None,name='view_payments'))
urlpatterns.append(path('fixture-expenses/',lambda r: None,name='view_expenses'))
urlpatterns.append(path('portal/',include(('client_portal.urls','portal'),namespace='portal')))
