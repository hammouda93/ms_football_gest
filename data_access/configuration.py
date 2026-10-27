"""Explicit integration configuration, separate from business and lab settings."""
from copy import deepcopy
import json


def integration_settings(databases, environment):
    """Add an alias only on explicit activation; never load dotenv or fetch secrets.

    The alias shares the physical PostgreSQL database, not its application
    transaction. Its role is not claimed to be read-only; the reader transaction
    enforces that. No credential or activation is provided by default.
    """
    enabled = environment.get('MSF_DATA_ACCESS_ENABLED','0')
    if enabled not in {'0','1'}:
        raise ValueError('Invalid data access activation configuration')
    try:
        credentials = json.loads(environment.get('MSF_DATA_ACCESS_CREDENTIALS_JSON','[]'))
        if not isinstance(credentials,list):
            raise ValueError()
    except (ValueError,TypeError,RecursionError):
        raise ValueError('Invalid data access credential configuration') from None
    if enabled == '1':
        default = databases.get('default',{})
        if default.get('ENGINE') != 'django.db.backends.postgresql':
            raise ValueError('Data access requires an explicit PostgreSQL database')
        alias = deepcopy(default)
        alias.update(ATOMIC_REQUESTS=False,CONN_MAX_AGE=0,TEST={'MIRROR':'default'})
        databases['data_access'] = alias
    return {'DATA_ACCESS_ENABLED':enabled=='1', 'DATA_ACCESS_CREDENTIALS':credentials,
            'DATA_ACCESS_STATEMENT_TIMEOUT_MS':1500,'DATA_ACCESS_MAX_RESPONSE_BYTES':262144,
            'DATA_ACCESS_MAX_CELL_BYTES':16384,
            'DATA_ACCESS_REQUESTS_PER_MINUTE':10,'DATA_ACCESS_GLOBAL_REQUESTS_PER_MINUTE':15,
            'DATA_ACCESS_RELEASE':environment.get('HEROKU_SLUG_COMMIT','unknown')}


def audit_logging(existing):
    """Preserve business loggers; write only the audit's already-sanitized JSON."""
    value = deepcopy(existing or {'version':1,'disable_existing_loggers':False})
    value.setdefault('formatters',{})['data_access_json'] = {'format':'%(message)s'}
    value.setdefault('handlers',{})['data_access_json'] = {
        'class':'logging.StreamHandler','formatter':'data_access_json'}
    value.setdefault('loggers',{})['data_access.audit'] = {
        'handlers':['data_access_json'],'level':'INFO','propagate':False}
    return value
