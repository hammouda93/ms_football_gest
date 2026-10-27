"""Server-side declarative read validation against policy-filtered runtime metadata.

This validator is one layer of the independent access boundary; authentication,
internal scope, PostgreSQL transaction and budgets are enforced by the views/engine.
"""
import json
from pathlib import Path

POLICY = json.loads((Path(__file__).parent / 'policy.json').read_text(encoding='utf-8'))


def validate(request, catalog):
    import datetime as dt
    from decimal import Decimal, InvalidOperation
    import re
    integer_bits = {'AutoField': 32, 'BigAutoField': 64, 'ImplicitAutoField': 64,
                    'IntegerField': 32, 'BigIntegerField': 64, 'SmallIntegerField': 16,
                    'SmallAutoField': 16, 'PositiveIntegerField': 32,
                    'PositiveSmallIntegerField': 16, 'PositiveBigIntegerField': 64}
    numeric = set(integer_bits) | {'DecimalField', 'FloatField'}
    text_types = {'CharField', 'TextField', 'EmailField', 'URLField'}
    allowed = {'entity', 'select', 'where', 'groupBy', 'metrics', 'orderBy', 'limit', 'offset'}
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError('Unknown request arguments')
    try:
        if len(json.dumps(request, allow_nan=False, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 32768:
            raise ValueError('Request too large')
    except (TypeError, OverflowError, RecursionError) as exc:
        raise ValueError('Invalid JSON request') from exc
    entity = request.get('entity')
    if not isinstance(entity, str) or entity not in catalog['models'] or entity not in POLICY['models']:
        raise ValueError('Entity is not reviewed for access')
    limit, offset = request.get('limit', 100), request.get('offset', 0)
    if type(limit) is not int or not 1 <= limit <= 500 or type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError('Pagination out of bounds')

    def resolve(path):
        if not isinstance(path, str) or len(path) > 180 or not re.fullmatch(r'[a-z][a-z0-9_]*(?:__[a-z][a-z0-9_]*)*', path):
            raise ValueError('Invalid field path')
        parts, current, many = path.split('__'), entity, []
        if len(parts) > 5:
            raise ValueError('Too many relation hops')
        for i, name in enumerate(parts):
            if current not in POLICY['models']:
                raise ValueError('Relation target not reviewed')
            model = catalog['models'][current]
            field = model['fields'].get(name)
            if field:
                if name not in POLICY['models'][current]:
                    raise ValueError('Field not reviewed')
            else:
                field = model['reverseRelations'].get(name)
                if not field or field['target'] not in POLICY['models'] or field['field'] not in POLICY['models'][field['target']]:
                    raise ValueError('Reverse relation not reviewed')
            if field.get('cardinality') == 'many':
                if i != 0 or len(parts) != 2:
                    raise ValueError('Aggregate direct child fields only; use separate reads for other grains')
                many.append('__'.join(parts[:i + 1]))
            if i < len(parts) - 1:
                current = field.get('target')
                if not current:
                    raise ValueError('Cannot traverse scalar')
            elif 'type' not in field or field.get('cardinality') == 'many' or len(many) > 1:
                raise ValueError('Scalar endpoint and at most one collection required')
        return field, many[0] if many else None

    def field_list(value, maximum):
        if not isinstance(value, list) or len(value) > maximum or any(not isinstance(x, str) for x in value) or len(set(value)) != len(value):
            raise ValueError('Invalid field list')
        return list(value)

    select = field_list(request.get('select', []), 40)
    groups = field_list(request.get('groupBy', []), 4)
    for path in select + groups:
        field, branch = resolve(path)
        if branch or path in groups and field['type'] in {'JSONField', 'BinaryField'}:
            raise ValueError('Collection projection or JSON grouping unavailable')
    metrics = request.get('metrics', [])
    if not isinstance(metrics, list) or len(metrics) > 10:
        raise ValueError('Invalid metrics')
    if metrics and select or groups and not metrics or not metrics and not select:
        raise ValueError('Use projection OR metrics with optional groups')
    aliases, branches, checked = set(), set(), []
    for item in metrics:
        if not isinstance(item, dict) or set(item) != {'alias', 'function', 'field'}:
            raise ValueError('Invalid metric')
        alias, function = item['alias'], item['function']
        if not isinstance(alias, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', alias) or '__' in alias or alias in groups or alias in aliases or alias in catalog['models'][entity]['fields'] or alias in catalog['models'][entity]['reverseRelations']:
            raise ValueError('Invalid or conflicting alias')
        if not isinstance(function, str) or function not in {'count', 'count_distinct', 'sum', 'avg', 'min', 'max'}:
            raise ValueError('Unknown metric function')
        field, branch = resolve(item['field'])
        if field['type'] in {'JSONField', 'BinaryField'} or function in {'sum', 'avg'} and field['type'] not in numeric:
            raise ValueError('Invalid metric type')
        if function in {'min', 'max'} and field['type'] not in numeric | text_types | {'DateField', 'DateTimeField'}:
            raise ValueError('Ordered metric type unavailable')
        aliases.add(alias)
        branches.add(branch)
        checked.append(dict(item))
    if len(branches) > 1:
        raise ValueError('Mixed aggregation grains: use separate reads')

    def scalar(field, value):
        kind = field['type']
        if value is None:
            return
        if kind in numeric or 'target' in field:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError('Numeric value required')
            if kind in integer_bits or 'target' in field:
                if type(value) is not int and (not isinstance(value, str) or len(value) > 20 or not re.fullmatch(r'(?:0|-?[1-9][0-9]*)', value)):
                    raise ValueError('Canonical integer required, without exponent or decimal notation')
                integer = int(value)
                effective_kind = kind
                if 'target' in field:
                    related = catalog['models'].get(field['target'], {})
                    primary = next((f for f in related.get('fields', {}).values() if f['primaryKey']), None)
                    effective_kind = primary['type'] if primary else 'BigIntegerField'
                bits = integer_bits.get(effective_kind, 64)
                lower = 0 if effective_kind.startswith('Positive') else -(2 ** (bits - 1))
                if not lower <= integer <= 2 ** (bits - 1) - 1:
                    raise ValueError('Integer outside documented field range')
                return
            try:
                number = Decimal(str(value))
                if not number.is_finite() or abs(number.adjusted()) > 308:
                    raise ValueError('Finite bounded number required')
            except InvalidOperation as exc:
                raise ValueError('Numeric value required') from exc
        elif kind == 'BooleanField':
            if type(value) is not bool:
                raise ValueError('Boolean required')
        elif kind in {'DateField', 'DateTimeField'}:
            if not isinstance(value, str):
                raise ValueError('ISO date required')
            if kind == 'DateTimeField':
                try:
                    # Python 3.10 does not accept the standard UTC Z suffix.
                    parsed = dt.datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
                    if parsed.utcoffset() is None:
                        raise ValueError
                except ValueError:
                    raise ValueError('ISO datetime with explicit UTC offset required') from None
            else:
                dt.date.fromisoformat(value)
        elif kind in text_types:
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError('Bounded text required')
        else:
            raise ValueError('Filter type unavailable')

    leaves = 0

    def condition(node, depth=0):
        nonlocal leaves
        if depth > 4 or not isinstance(node, dict):
            raise ValueError('Filter tree out of bounds')
        if len(node) == 1 and next(iter(node)) in {'all', 'any', 'not'}:
            key = next(iter(node))
            if key == 'not':
                return {key: condition(node[key], depth + 1)}
            if not isinstance(node[key], list) or not 1 <= len(node[key]) <= 20:
                raise ValueError('Invalid filter group')
            return {key: [condition(x, depth + 1) for x in node[key]]}
        if set(node) != {'field', 'op', 'value'}:
            raise ValueError('Invalid condition')
        leaves += 1
        if leaves > 20:
            raise ValueError('Too many filters')
        field, branch = resolve(node['field'])
        if branch:
            raise ValueError('Collection filters require separate reads')
        op, value = node['op'], node['value']
        if not isinstance(op, str) or op not in {'eq', 'ne', 'in', 'isnull', 'gt', 'gte', 'lt', 'lte', 'icontains', 'startswith'}:
            raise ValueError('Unknown comparison')
        if op in {'gt', 'gte', 'lt', 'lte'} and (value is None or field['type'] == 'BooleanField'):
            raise ValueError('Invalid ordered comparison')
        if value is None and op not in {'eq', 'ne'}:
            raise ValueError('Use isnull for null checks')
        if op == 'isnull':
            if type(value) is not bool:
                raise ValueError('isnull requires boolean')
        elif op == 'in':
            if not isinstance(value, list) or not 1 <= len(value) <= 100:
                raise ValueError('Invalid membership list')
            for v in value:
                if v is None:
                    raise ValueError('Use a separate isnull condition')
                scalar(field, v)
        else:
            if op in {'icontains', 'startswith'} and field['type'] not in text_types:
                raise ValueError('Text comparison required')
            scalar(field, value)
        return dict(node)

    where = condition(request['where']) if 'where' in request else None
    order = field_list(request.get('orderBy', []), 5)
    if not order:
        order = list(groups) if metrics else ['id']
    for entry in order:
        path = entry[1:] if entry.startswith('-') else entry
        if metrics:
            if path not in groups and path not in aliases:
                raise ValueError('Order must use a group or metric')
        else:
            field, branch = resolve(path)
            if branch or field['type'] in {'JSONField', 'BinaryField'}:
                raise ValueError('Ordering type unavailable')
    for tie in groups if metrics else ['id']:
        if tie not in [x.lstrip('-') for x in order]:
            order.append(tie)
    return {'mode': 'read', 'entity': entity, 'select': select, 'where': where,
            'groupBy': groups, 'metrics': checked, 'orderBy': order, 'limit': limit,
            'offset': offset, 'collection': next(iter(branches), None)}
