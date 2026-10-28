"""Fictional hash-only settings; no application/database imports."""
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from actions.mount import configure

SCOPES = ['catalogue', 'prepare', 'status', 'op:player.create', 'op:organization.link',
          'op:video.order', 'op:player.amend', 'op:video.amend']

def config():
    return {'enabled': True, 'credentials': {
        hashlib.sha256(b'FICTION-pilot-only').hexdigest(): {
            'actor': 19, 'scopes': list(SCOPES),
            'expires': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            'revoked': False}}}

def mount(value=None):
    reader = {'enabled': True, 'credentials': {'FICTION-reader-hash': 'preserved'}}
    namespace = {'INSTALLED_APPS': ['data_access'],
                 'MIDDLEWARE': ['django.middleware.security.SecurityMiddleware',
                                'data_access.boundary.ReaderBoundary', 'fiction.SessionMiddleware'],
                 'HERMES_READER': reader}
    env = {} if value is None else {'MSF_ACTIONS_PILOT_CONFIG': json.dumps(value)}
    with patch.dict('os.environ', env, clear=True):
        configure(namespace)
    return namespace

class ConfigTests(unittest.TestCase):
    def test_restart_after_24_hours_soft_disables_expired_writer_only(self):
        value = config()
        start = datetime.now(timezone.utc)
        digest = next(iter(value['credentials']))
        value['credentials'][digest]['expires'] = (start + timedelta(hours=24)).isoformat()
        with patch('actions.mount.datetime', wraps=datetime) as clock:
            clock.now.return_value = start + timedelta(hours=24, seconds=1)
            result = mount(value)
        self.assertIs(result['ACTIONS_ENABLED'], False)
        self.assertEqual(result['ACTIONS_CREDENTIALS'], {})
        self.assertEqual(result['ACTIONS_PILOT_DIAGNOSTIC'], 'actions_pilot_disabled')
        self.assertEqual(result['HERMES_READER']['credentials'], {'FICTION-reader-hash': 'preserved'})
        self.assertIs(result['ACTIONS_EXECUTE_ENABLED'], False)

    def test_explicit_hash_only_opt_in_and_reader_intact(self):
        value = config()
        result = mount(value)
        self.assertIs(result['ACTIONS_ENABLED'], True)
        self.assertEqual(result['ACTIONS_CREDENTIALS'], value['credentials'])
        self.assertIs(result['ACTIONS_EXECUTE_ENABLED'], False)
        self.assertEqual(result['ACTIONS_APPROVAL_KEY'], '')
        self.assertEqual(result['MIDDLEWARE'], [
            'django.middleware.security.SecurityMiddleware', 'actions.pilot.PrepareOnlyBoundary',
            'data_access.boundary.ReaderBoundary', 'fiction.SessionMiddleware'])
        self.assertEqual(result['HERMES_READER']['credentials'], {'FICTION-reader-hash': 'preserved'})
        self.assertEqual(result['INSTALLED_APPS'], ['data_access', 'actions'])

    def test_rejects_types_unknown_keys_raw_secrets_and_long_ttl_without_echo(self):
        import copy
        base = config()
        digest = next(iter(base['credentials']))
        variants = [[], None, True, {'enabled': 'true', 'credentials': {}},
                    dict(base, approval_key='FICTION-secret-do-not-echo'),
                    dict(base, execute_enabled=True), dict(base, credentials=[]),
                    dict(base, credentials={'FICTION-raw-secret': base['credentials'][digest]}),
                    {'enabled': False, 'credentials': base['credentials']}]
        for field, value in [('actor', True), ('actor', 0), ('scopes', SCOPES + ['execute']),
                             ('scopes', SCOPES + [SCOPES[0]]), ('scopes', 'prepare'),
                             ('revoked', 0), ('secret', 'FICTION-secret-do-not-echo'),
                             ('expires', '2099-01-01T00:00:00+00:00'),
                             ('expires', '2026-10-28T12:00:00')]:
            value_config = copy.deepcopy(base)
            value_config['credentials'][digest][field] = value
            variants.append(value_config)
        for value in variants:
            with self.subTest(value_type=type(value).__name__):
                with patch.dict('os.environ', {'MSF_ACTIONS_PILOT_CONFIG': json.dumps(value)}, clear=True):
                    namespace = {'INSTALLED_APPS': [], 'MIDDLEWARE': ['django.middleware.security.SecurityMiddleware']}
                    configure(namespace)
                    self.assertIs(namespace['ACTIONS_ENABLED'], False)
                    self.assertEqual(namespace['ACTIONS_CREDENTIALS'], {})
                    self.assertEqual(namespace['ACTIONS_PILOT_DIAGNOSTIC'], 'actions_pilot_config_invalid')
                    self.assertIs(namespace['ACTIONS_EXECUTE_ENABLED'], False)
                    self.assertEqual(namespace['ACTIONS_APPROVAL_KEY'], '')
        for raw in ['{"enabled":false,"enabled":true,"credentials":{}}',
                    '{FICTION-secret-do-not-echo', 'x' * 16001, '[' * 1001]:
            with patch.dict('os.environ', {'MSF_ACTIONS_PILOT_CONFIG': raw}, clear=True):
                namespace = {'INSTALLED_APPS': [], 'MIDDLEWARE': ['django.middleware.security.SecurityMiddleware']}
                configure(namespace)
                self.assertIs(namespace['ACTIONS_ENABLED'], False)
                self.assertEqual(namespace['ACTIONS_CREDENTIALS'], {})
                self.assertEqual(namespace['ACTIONS_PILOT_DIAGNOSTIC'], 'actions_pilot_config_invalid')

    def test_revoked_and_expired_entries_never_reenable_writer(self):
        value = config()
        credential = next(iter(value['credentials'].values()))
        credential['revoked'] = True
        result = mount(value)
        self.assertIs(result['ACTIONS_ENABLED'], False)
        self.assertEqual(result['ACTIONS_CREDENTIALS'], {})
        credential['actor'] = True
        result = mount(value)
        self.assertEqual(result['ACTIONS_PILOT_DIAGNOSTIC'], 'actions_pilot_config_invalid')
        self.assertIs(result['ACTIONS_ENABLED'], False)

    def test_default_closed_without_credentials(self):
        result = mount()
        self.assertIs(result['ACTIONS_ENABLED'], False)
        self.assertEqual(result['ACTIONS_CREDENTIALS'], {})
        self.assertIs(result['ACTIONS_EXECUTE_ENABLED'], False)

if __name__ == '__main__': unittest.main(verbosity=2)
