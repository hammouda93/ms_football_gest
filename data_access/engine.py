"""Execute validated, fixed-operator ORM reads in a short PostgreSQL transaction."""
from contextlib import contextmanager
from copy import deepcopy
import time
from django.apps import apps
from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q, Count, Sum, Avg, Min, Max
from django.db.models import F, Func, IntegerField, TextField
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from .contract import validate
from .metadata import catalog


class BusyError(Exception):
    pass


class ResponseBudgetError(Exception):
    pass


def bounded_rows(qs, plan):
    # Size probes run in SQL before projecting text/JSON values into Python.
    columns = plan['groupBy'] + [m['alias'] for m in plan['metrics']] if plan['metrics'] else plan['select']
    probes = {
        f'_msf_size_{i}': Coalesce(Func(Cast(F(name), TextField()), function='octet_length', output_field=IntegerField()), 0)
        for i, name in enumerate(columns)
    }
    window = slice(plan['offset'], plan['offset'] + plan['limit'] + 1)
    sizes = list(qs.annotate(**probes).values(*probes)[window])
    max_cell = getattr(settings, 'DATA_ACCESS_MAX_CELL_BYTES', 65536)
    # Conservative escape expansion (up to 6 bytes in JSON for one byte).
    max_total = getattr(settings, 'DATA_ACCESS_MAX_RESPONSE_BYTES', 1024 * 1024)
    if any(size > max_cell for row in sizes for size in row.values()) or sum(sum(row.values()) for row in sizes) * 6 > max_total - 4096:
        raise ResponseBudgetError()
    return list(qs[window])


@contextmanager
def read_transaction():
    if 'data_access' not in settings.DATABASES:
        raise RuntimeError('Explicit analytical connection is required')
    connection = connections['data_access']
    if connection.vendor != 'postgresql':
        raise RuntimeError('PostgreSQL is required for the read boundary')
    if connection.settings_dict.get('ATOMIC_REQUESTS', False):
        raise RuntimeError('Analytical connection must disable ATOMIC_REQUESTS')
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError('Read access must not inherit an analytical transaction')
    try:
        with transaction.atomic(using='data_access'):
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(getattr(settings, 'DATA_ACCESS_STATEMENT_TIMEOUT_MS', 2000))])
                cursor.execute("SELECT set_config('lock_timeout', '100', true)")
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [76430021])
                if not cursor.fetchone()[0]:
                    raise BusyError('Another analytical read is already running')
            try:
                yield
            finally:
                transaction.set_rollback(True, using='data_access')
    finally:
        connection.close()


def predicate(node):
    if node is None:
        return Q()
    if 'not' in node:
        return ~predicate(node['not'])
    for key in ('all', 'any'):
        if key in node:
            result = predicate(node[key][0])
            for child in node[key][1:]:
                result = result & predicate(child) if key == 'all' else result | predicate(child)
            return result
    lookups = {'eq': 'exact', 'ne': 'exact', 'in': 'in', 'isnull': 'isnull', 'gt': 'gt',
               'gte': 'gte', 'lt': 'lt', 'lte': 'lte', 'icontains': 'icontains', 'startswith': 'startswith'}
    result = Q(**{node['field'] + '__' + lookups[node['op']]: node['value']})
    return ~result if node['op'] == 'ne' else result


def compile_queryset(plan):
    model = apps.get_model(plan['entity'])
    qs = model.objects.using('data_access').filter(predicate(plan['where'])).order_by()
    if plan['metrics']:
        functions = {'count': Count, 'count_distinct': Count, 'sum': Sum, 'avg': Avg, 'min': Min, 'max': Max}
        annotations = {m['alias']: functions[m['function']](m['field'], **({'distinct': True} if m['function'] == 'count_distinct' else {})) for m in plan['metrics']}
        if not plan['groupBy']:
            return qs, annotations
        return qs.values(*plan['groupBy']).annotate(**annotations).order_by(*plan['orderBy']), None
    return qs.values(*plan['select']).order_by(*plan['orderBy']), None


def execute(query):
    metadata = catalog()
    plan = validate(deepcopy(query), metadata)
    started = time.monotonic()
    with read_transaction():
        read_at = timezone.now().isoformat()
        qs, aggregate = compile_queryset(plan)
        if aggregate is not None:
            if plan['offset'] == 0:
                sizes = {f'_msf_size_{i}': Coalesce(Func(Cast(expression, TextField()), function='octet_length', output_field=IntegerField()), 0)
                         for i, expression in enumerate(aggregate.values())}
                measured = qs.aggregate(**sizes)
                if any(size > getattr(settings, 'DATA_ACCESS_MAX_CELL_BYTES', 65536) for size in measured.values()) or sum(measured.values()) * 6 > getattr(settings, 'DATA_ACCESS_MAX_RESPONSE_BYTES', 1024 * 1024) - 4096:
                    raise ResponseBudgetError()
                rows = [qs.aggregate(**aggregate)]
            else:
                rows = []
            more = False
        else:
            rows = bounded_rows(qs, plan)
            more = len(rows) > plan['limit']
            rows = rows[:plan['limit']]
    return {'readAt': read_at, 'schemaFingerprint': metadata['schemaFingerprint'], 'rows': rows,
            'entity': plan['entity'], 'limit': plan['limit'], 'offset': plan['offset'],
            'hasMore': more, 'nextOffset': plan['offset'] + len(rows) if more else None,
            'completePage': True, 'consistency': 'repeatable-read within this request; separate requests can differ',
            'durationMs': round((time.monotonic() - started) * 1000, 3),
            'release': getattr(settings, 'DATA_ACCESS_RELEASE', 'unknown'), 'mode': 'read-only'}
