"""Import delivered settings bytes, not a rewritten lab mount."""
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parent

class PackagedSettingsTests(unittest.TestCase):
    def test_real_settings_mount_closed_preserves_reader_and_business_middleware(self):
        import platform
        platform.system()
        import celery.schedules
        import dotenv
        import dj_database_url
        sys.path[:0] = [str(ROOT/'deployment-overlay'), str(ROOT.parent/'lot-06/app')]
        from test_config import config
        from datetime import datetime, timedelta, timezone
        expired = config()
        next(iter(expired['credentials'].values()))['expires'] = (datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
        import json
        cases = [{}, {'MSF_ACTIONS_PILOT_CONFIG': '{FICTION-do-not-echo'},
                 {'MSF_ACTIONS_PILOT_CONFIG': json.dumps(expired)}]
        for environment in cases:
            with patch.dict(os.environ, environment, clear=True), patch.object(dotenv,'load_dotenv',return_value=False), patch.object(dj_database_url,'config',return_value={}):
                value = runpy.run_path(str(ROOT/'deployment-overlay/ms_football_gest/settings.py'))
            self.assertIs(value['ACTIONS_ENABLED'], False)
            self.assertEqual(value['ACTIONS_CREDENTIALS'], {})
            self.assertIs(value['ACTIONS_EXECUTE_ENABLED'], False)
            self.assertIn('data_access', value['INSTALLED_APPS'])
        self.assertIs(value['ACTIONS_ENABLED'], False)
        self.assertIs(value['ACTIONS_EXECUTE_ENABLED'], False)
        self.assertEqual(value['ACTIONS_CREDENTIALS'], {})
        self.assertEqual(value['ACTIONS_APPROVAL_KEY'], '')
        self.assertEqual(value['MIDDLEWARE'][:3], ['django.middleware.security.SecurityMiddleware',
                         'actions.pilot.PrepareOnlyBoundary', 'data_access.middleware.ReaderIsolationMiddleware'])
        self.assertIn('gestion_joueurs.middleware.CurrentUserMiddleware',value['MIDDLEWARE'])
        self.assertEqual(value['INSTALLED_APPS'].count('actions'),1)
        self.assertIn('data_access',value['INSTALLED_APPS'])
        self.assertFalse(value['DATA_ACCESS_ENABLED'])
        self.assertNotIn('data_access',value['DATABASES'])
        print('PACKAGED_SETTINGS_IMPORT', {'actionsClosed':True,'readerPreserved':True,'fullAppStartup':False})

if __name__ == '__main__': unittest.main(verbosity=2)
