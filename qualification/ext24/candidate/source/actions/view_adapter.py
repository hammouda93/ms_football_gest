"""Fixed internal request, not client-controlled view dispatch."""
from django.test import RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

def request_for(actor_id,data):
 request=RequestFactory().post('/internal-reviewed-adapter/',data)
 request.user=User.objects.get(pk=actor_id,is_active=True)
 request.session={}
 request._messages=FallbackStorage(request)
 return request
