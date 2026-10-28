"""Offline real Django boundary with a socket/process deny guard."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent
if __name__ == '__main__':
    from django.conf import settings
    sys.path[:0] = [str(ROOT), str(ROOT.parent / 'action-06'), str(ROOT.parent / 'action-06/source')]
    import platform
    platform.system()
    from celery.app.task import Task
    import lab_settings
    values = {k: getattr(lab_settings, k) for k in dir(lab_settings) if k.isupper()}
    values['DATABASES'] = {'default': {'ENGINE': 'django.db.backends.dummy'}}
    settings.configure(**values)
    import dotenv
    dotenv.load_dotenv = lambda *a, **kw: False
    def guard(event, args):
        if event in ('socket.connect', 'subprocess.Popen', 'os.system'):
            raise AssertionError('offline boundary attempted I/O')
    sys.addaudithook(guard)
    import django
    django.setup()
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from actions.http import OperationalWriterBoundary
try:
    from actions.pilot import PrepareOnlyBoundary
except ModuleNotFoundError:
    PrepareOnlyBoundary = OperationalWriterBoundary

class BoundaryTests(unittest.TestCase):
    def test_execute_denied_before_auth_database_even_if_flags_or_credentials_grant_it(self):
        from django.db import connection
        request = RequestFactory().post('/actions/v1/execute', '{}', content_type='application/json')
        with override_settings(ACTIONS_ENABLED=True, ACTIONS_EXECUTE_ENABLED=True, ACTIONS_APPROVAL_KEY='FICTION-signing-not-used'):
            with patch.object(connection, 'get_autocommit', side_effect=AssertionError('SQL boundary reached')):
                response = PrepareOnlyBoundary(lambda r: self.fail('downstream reached'))(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, b'{"error": "execute_disabled_pilot"}')
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_reader_namespace_passes_through_without_actor_session_or_sql(self):
        for path in ['/integrations/data/v1/schema/', '/integrations/data/v1/query/', '/ordinary/', '/actions-other']:
            request = RequestFactory().get(path)
            expected = HttpResponse('FICTION reader unchanged')
            self.assertIs(PrepareOnlyBoundary(lambda r: expected)(request), expected)

if __name__ == '__main__': unittest.main(verbosity=2)
