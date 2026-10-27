"""Closed-by-default authenticated read HTTP views. No production configuration."""
import json
import time
import uuid
from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from django.db import DatabaseError, connections, transaction
from django.views.decorators.csrf import csrf_exempt
from .metadata import catalog
from .engine import execute, BusyError, ResponseBudgetError
from .contract import validate
from .access import authenticate_request, reserve_budget, emit_audit, fingerprint, AccessDenied


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def secured(view):
    @wraps(view)
    def call(request):
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        request.data_access_id = request_id
        request.data_access_audit = {'requestId': request_id}
        try:
            principal = authenticate_request(request)
            request.data_access_principal = principal
            request.data_access_audit['principalId'] = principal['id']
            reserve_budget(principal['id'])
            response = view(request)
        except AccessDenied as error:
            response = JsonResponse({'error': {'code': error.code, 'message': error.message}, 'requestId': request_id}, status=error.status)
            if hasattr(error, 'retry_after'):
                response['Retry-After'] = str(error.retry_after)
        except Exception:
            # Fail closed. Do not log exception messages, query values or credentials.
            response = JsonResponse({'error': {'code': 'access_unavailable', 'message': 'Technical access is unavailable.'}, 'requestId': request_id}, status=503)
        finally:
            if 'data_access' in connections.databases:
                connection = connections['data_access']
                if not connection.in_atomic_block and (connection.connection is None or connection.get_autocommit()):
                    connection.close()
        payload = json.loads(response.content)
        code = payload.get('error', {}).get('code', 'ok')
        request.data_access_audit.update(status=response.status_code, code=code,
            durationMs=round((time.monotonic()-started)*1000, 3))
        emit_audit(request.data_access_audit)
        if 'requestId' not in payload:
            response.content = json.dumps({**payload, 'requestId': request_id}, allow_nan=False)
        response['Cache-Control'] = 'no-store, private'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    return call


@transaction.non_atomic_requests(using='default')
@secured
def schema(request):
    if request.method != 'GET':
        return JsonResponse({'error': {'code': 'method_not_allowed'}}, status=405)
    metadata = catalog()
    request.data_access_audit['schemaFingerprint'] = metadata['schemaFingerprint']
    return JsonResponse({**metadata, 'requestId': request.data_access_id})


@csrf_exempt
@transaction.non_atomic_requests(using='default')
@secured
def query(request):
    if request.method != 'POST':
        return JsonResponse({'error': {'code': 'method_not_allowed'}}, status=405)
    content_length = request.META.get('CONTENT_LENGTH')
    if content_length is not None and (not isinstance(content_length, str) or not content_length.isascii() or not content_length.isdecimal()):
        return JsonResponse({'error': {'code': 'invalid_body'}, 'requestId': request.data_access_id}, status=400)
    content_length = (content_length or '0').lstrip('0') or '0'
    if request.content_type != 'application/json' or len(content_length) > 5 or int(content_length) > 32768:
        return JsonResponse({'error': {'code': 'invalid_body'}, 'requestId': request.data_access_id}, status=413)
    if 'CONTENT_LENGTH' in request.META:
        # Django reparses this value when request.body is first accessed.
        request.META['CONTENT_LENGTH'] = content_length
    if len(request.body) > 32768:
        return JsonResponse({'error': {'code': 'invalid_body'}}, status=413)
    try:
        value = json.loads(request.body, object_pairs_hook=unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        metadata = catalog()
        plan = validate(value, metadata)
        # Names enter the audit only AFTER complete path/type/policy validation.
        request.data_access_audit.update(queryHash=fingerprint(value), entity=plan['entity'],
            schemaFingerprint=metadata['schemaFingerprint'],
            fields=sorted(set(plan['select'] + plan['groupBy'] + [m['field'] for m in plan['metrics']])))
        result = execute(value)
        request.data_access_audit['rowCount'] = len(result['rows'])
        response = JsonResponse({**result, 'requestId': request.data_access_id}, json_dumps_params={'allow_nan': False})
        if len(response.content) > getattr(settings, 'DATA_ACCESS_MAX_RESPONSE_BYTES', 1024 * 1024):
            return JsonResponse({'error': {'code': 'response_too_large', 'message': 'Select fewer rows or fields.'}}, status=413)
        return response
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        return JsonResponse({'error': {'code': 'invalid_query', 'message': 'Invalid, unauthorized or excessive query; check the published schema and contract.'}, 'requestId': request.data_access_id}, status=400)
    except ResponseBudgetError:
        return JsonResponse({'error': {'code': 'response_too_large', 'message': 'Select fewer rows or fields.'}, 'requestId': request.data_access_id}, status=413)
    except BusyError:
        return JsonResponse({'error': {'code': 'busy', 'message': 'Analytical read already in progress.'}, 'requestId': request.data_access_id}, status=429)
    except DatabaseError:
        return JsonResponse({'error': {'code': 'database_read_failed', 'message': 'Read cancelled or failed; no data changed.'}, 'requestId': request.data_access_id}, status=504)
