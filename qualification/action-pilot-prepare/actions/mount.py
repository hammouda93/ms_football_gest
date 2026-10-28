"""Dedicated prepare-only pilot; no credentials or activation by default."""
import json
import os
import re
from datetime import datetime, timezone

SCOPES = frozenset(('catalogue', 'prepare', 'status', 'op:player.create',
                    'op:organization.link', 'op:video.order', 'op:player.amend', 'op:video.amend'))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _configuration():
    try:
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
            if ttl <= 0 or ttl > 86400:
                raise ValueError()
            clean[digest] = {'actor': actor, 'scopes': list(scopes), 'expires': expires, 'revoked': credential['revoked']}
        return {'enabled': enabled, 'credentials': clean}
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('actions_pilot_config_invalid') from None


def configure(namespace):
    value = _configuration()
    namespace['INSTALLED_APPS'] = [*namespace['INSTALLED_APPS'], 'actions']
    middleware = list(namespace['MIDDLEWARE'])
    middleware.insert(middleware.index('django.middleware.security.SecurityMiddleware') + 1,
                      'actions.pilot.PrepareOnlyBoundary')
    namespace['MIDDLEWARE'] = middleware
    namespace['ACTIONS_ENABLED'] = value['enabled']
    namespace['ACTIONS_CREDENTIALS'] = value['credentials']
    namespace['ACTIONS_EXECUTE_ENABLED'] = False
    namespace['ACTIONS_APPROVAL_KEY'] = ''
