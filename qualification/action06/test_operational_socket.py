"""Replay unchanged socket assertions through the new operational boundary."""
from django.conf import settings
from django.test import override_settings
from test_socket import SocketTests

class OperationalSocketTests(SocketTests):
    def setUp(self):
        config=override_settings(MIDDLEWARE=[m.replace('actions.http.WriterBoundary','actions.http.OperationalWriterBoundary') for m in settings.MIDDLEWARE],ACTIONS_QUOTA_GLOBAL=10000,ACTIONS_QUOTA_IDENTITY=10)
        config.enable();self.addCleanup(config.disable)
