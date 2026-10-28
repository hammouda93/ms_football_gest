"""Production-boundary regression: caller transaction remains owned by caller."""
import unittest
from django.db import connection,transaction
from django.test import RequestFactory,override_settings
from actions.http import WriterBoundary

class OperationalTests(unittest.TestCase):
    def test_closed_mount_cannot_be_enabled_by_environment(self):
        import importlib.util,os
        from pathlib import Path
        path=Path(__file__).parent/'actions/mount.py'
        self.assertTrue(path.exists(),'closed deployment mount is missing')
        spec=importlib.util.spec_from_file_location('closed_mount',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        ns={'INSTALLED_APPS':['data_access'],'MIDDLEWARE':['django.middleware.security.SecurityMiddleware','data_access.middleware.ReaderIsolationMiddleware','django.contrib.sessions.middleware.SessionMiddleware']}
        module.configure(ns)
        self.assertFalse(ns['ACTIONS_ENABLED'])
        self.assertEqual(ns['ACTIONS_CREDENTIALS'],{})
        self.assertEqual(ns['ACTIONS_APPROVAL_KEY'],'')
        self.assertEqual(ns['MIDDLEWARE'][1],'actions.http.OperationalWriterBoundary')
        self.assertEqual(ns['MIDDLEWARE'][2:3],['data_access.middleware.ReaderIsolationMiddleware'])

    def test_closed_real_http_namespace_never_queries_database(self):
        from django.conf import settings
        from django.test import Client
        middleware=[x.replace('actions.http.WriterBoundary','actions.http.OperationalWriterBoundary') for x in settings.MIDDLEWARE]
        def forbidden(*args):raise AssertionError('closed writer attempted SQL')
        with override_settings(MIDDLEWARE=middleware,ACTIONS_ENABLED=False),connection.execute_wrapper(forbidden):
            for route in ['catalogue','prepare','execute','status','missing']:
                response=Client().get('/actions/v1/'+route)
                self.assertEqual(response.status_code,403)
                self.assertEqual(response.json(),{'error':'writer_disabled'})
                self.assertEqual(response['Cache-Control'],'no-store')

    def test_manual_caller_transaction_is_preserved(self):
        from actions.http import OperationalWriterBoundary
        request=RequestFactory().get('/actions/v1/catalogue')
        connection.set_autocommit(False)
        try:
            with override_settings(ACTIONS_ENABLED=True):
                response=OperationalWriterBoundary(lambda r:None)(request)
            self.assertEqual(response.status_code,409)
            self.assertFalse(connection.get_autocommit())
            with connection.cursor() as c:c.execute('SELECT 1');self.assertEqual(c.fetchone(),(1,))
        finally:
            connection.rollback();connection.set_autocommit(True)

    def test_external_transaction_is_refused_before_dispatch(self):
        from actions import http
        boundary=getattr(http,'OperationalWriterBoundary',WriterBoundary)(lambda r:None)
        request=RequestFactory().get('/actions/v1/catalogue')
        with override_settings(ACTIONS_ENABLED=True),transaction.atomic():
            response=boundary(request)
            self.assertEqual(response.status_code,409)
            self.assertEqual(__import__('json').loads(response.content),{'error':'transaction_owned_externally'})
            self.assertTrue(connection.in_atomic_block)
            with connection.cursor() as c:c.execute('SELECT 1');self.assertEqual(c.fetchone(),(1,))
