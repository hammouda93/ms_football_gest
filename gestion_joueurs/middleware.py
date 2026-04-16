from django.utils.deprecation import MiddlewareMixin
from .utils import set_current_user

class CurrentUserMiddleware(MiddlewareMixin):
    def process_request(self, request):
        set_current_user(request.user)