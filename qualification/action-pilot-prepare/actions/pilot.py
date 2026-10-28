"""Pilot denies execution unconditionally, ahead of authentication and SQL."""
from .http import OperationalWriterBoundary, respond


class PrepareOnlyBoundary(OperationalWriterBoundary):
    def __call__(self, request):
        if request.path == '/actions/v1/execute':
            return respond({'error': 'execute_disabled_pilot'}, 403)
        return super().__call__(request)

    def authorized_dispatch(self, request, credential, operation):
        if operation == 'execute':
            return respond({'error': 'execute_disabled_pilot'}, 403)
        return super().authorized_dispatch(request, credential, operation)
