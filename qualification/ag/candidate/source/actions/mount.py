"""Dedicated prepare-only pilot; no credentials or activation by default."""
import json
import os
import re
from datetime import datetime, timezone

# Closed reviewed allowlist; registry imports require Django's populated app registry.
APPROVED_OPERATIONS = frozenset(('player.create', 'organization.link', 'video.order',
    'player.amend', 'video.amend', 'organization.details.amend', 'prospect.details.amend',
    'player.profile.create', 'organization.profile.create', 'organization.profile.amend',
    'prospect.profile.amend', 'player.profile.amend', 'video.status.transition',
    'video.workflow.transition'))
SCOPES = frozenset(('catalogue', 'prepare', 'status', 'execute', 'verify')) | frozenset(
    'op:' + name for name in APPROVED_OPERATIONS)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _configuration(raw=None):
    try:
        if raw is None:
            raw = os.environ.get('MSF_ACTIONS_PILOT_CONFIG', '{"enabled":false,"credentials":{}}')
        if len(raw) > 16000:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != {'enabled', 'credentials'}:
            raise ValueError()
        enabled, credentials = value['enabled'], value['credentials']
        if type(enabled) is not bool or type(credentials) is not dict or len(credentials) > 8:
            raise ValueError()
        if (not enabled and credentials) or (enabled and not credentials):
            raise ValueError()
        clean = {}
        for digest, credential in credentials.items():
            if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError()
            if type(credential) is not dict or set(credential) != {'actor', 'scopes', 'expires', 'revoked'}:
                raise ValueError()
            actor, scopes = credential['actor'], credential['scopes']
            if type(actor) is not int or not 0 < actor <= 2147483647 or type(credential['revoked']) is not bool:
                raise ValueError()
            if (type(scopes) is not list or any(type(scope) is not str for scope in scopes)
                    or len(set(scopes)) != len(scopes) or not set(scopes) <= SCOPES
                    or not {'catalogue', 'prepare', 'status'} <= set(scopes)):
                raise ValueError()
            expires = credential['expires']
            if type(expires) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?[+-]\d\d:\d\d', expires):
                raise ValueError()
            ttl = (datetime.fromisoformat(expires) - datetime.now(timezone.utc)).total_seconds()
            if ttl > 86400:
                raise ValueError()
            if ttl <= 0 or credential['revoked']:
                continue
            clean[digest] = {'actor': actor, 'scopes': list(scopes), 'expires': expires, 'revoked': credential['revoked']}
        return {'enabled': enabled and bool(clean), 'credentials': clean}
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('actions_pilot_config_invalid') from None


def valid_binding(binding):
    """Exact per-mission permit, never a wildcard service permission."""
    import uuid
    try:
        return (type(binding) is dict and set(binding) == {'plan_id', 'digest', 'actor', 'operations'}
            and type(binding['plan_id']) is str and str(uuid.UUID(binding['plan_id'])) == binding['plan_id']
            and type(binding['digest']) is str and re.fullmatch('[0-9a-f]{64}', binding['digest']) is not None
            and type(binding['actor']) is int and 0 < binding['actor'] <= 2147483647
            and type(binding['operations']) is list and 1 <= len(binding['operations']) <= 12
            and all(type(op) is str and op in APPROVED_OPERATIONS for op in binding['operations']))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def execute_configuration():
    """Dedicated opt-in; malformed or incomplete configuration closes execute only."""
    import uuid
    try:
        if os.environ.get('MSF_ACTIONS_EXECUTE_ENABLED') != 'true':
            raise ValueError()
        key = os.environ.get('MSF_ACTIONS_APPROVAL_KEY', '')
        if type(key) is not str or len(key) < 32:
            raise ValueError()
        raw = os.environ.get('MSF_ACTIONS_EXECUTE_BINDING', '')
        if len(raw) > 1000:
            raise ValueError()
        binding = json.loads(raw, object_pairs_hook=_unique)
        if not valid_binding(binding):
            raise ValueError()
        return True, key, binding
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return False, '', {}


def configure(namespace):
    try:
        value = _configuration()
        diagnostic = '' if value['enabled'] else 'actions_pilot_disabled'
    except ValueError:
        value = {'enabled': False, 'credentials': {}}
        diagnostic = 'actions_pilot_config_invalid'
    namespace['INSTALLED_APPS'] = [*namespace['INSTALLED_APPS'], 'actions']
    middleware = list(namespace['MIDDLEWARE'])
    middleware.insert(middleware.index('django.middleware.security.SecurityMiddleware') + 1,
                      'actions.pilot.PrepareOnlyBoundary')
    namespace['MIDDLEWARE'] = middleware
    namespace['ACTIONS_ENABLED'] = value['enabled']
    namespace['ACTIONS_PILOT_DIAGNOSTIC'] = diagnostic
    namespace['ACTIONS_CREDENTIALS'] = value['credentials']
    enabled, key, binding = execute_configuration()
    enabled = enabled and value['enabled']
    namespace['ACTIONS_EXECUTE_ENABLED'] = enabled
    namespace['ACTIONS_APPROVAL_KEY'] = key if enabled else ''
    namespace['ACTIONS_EXECUTE_BINDING'] = binding if enabled else {}
    from copy import deepcopy
    verification = deepcopy(namespace['DATABASES']['default'])
    verification.update(ATOMIC_REQUESTS=False, CONN_MAX_AGE=0)
    namespace['DATABASES']['verification'] = verification
    verification_key = os.environ.get('MSF_ACTIONS_VERIFICATION_KEY', '')
    namespace['ACTIONS_VERIFICATION_KEY'] = verification_key if len(verification_key) >= 32 else ''
