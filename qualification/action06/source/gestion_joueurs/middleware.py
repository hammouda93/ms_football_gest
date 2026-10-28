from .utils import actor_context

class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        with actor_context(request.user):
            return self.get_response(request)