"""Synchronous WSGI reader boundary, inside SecurityMiddleware, before sessions."""


class ReaderIsolationMiddleware:
    """Dispatch only the technical namespace; leave other requests untouched."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        prefix = '/integrations/data/v1/'
        if path != prefix[:-1] and not path.startswith(prefix):
            return self.get_response(request)
        # Call the existing secured views, not their unwrapped implementations.
        # This bypasses default ATOMIC_REQUESTS, never the engine's read boundary.
        if path == prefix + 'schema/':
            from .views import schema
            return schema(request)
        if path == prefix + 'query/':
            from .views import query
            return query(request)
        from django.http import JsonResponse
        response = JsonResponse({'error': {'code': 'not_found'}}, status=404)
        response['Cache-Control'] = 'no-store, private'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
