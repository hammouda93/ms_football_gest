"""Native Hermes MS Football writer; signer confined to trusted plugin code."""
import json
import urllib.error
import urllib.request
from .native_approval import NativeConsent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# Fixed source allowlist: no URL, hostname, path or port supplied by the model/config.
TARGETS = {'production': 'https://msfootball-1a882b44ed52.herokuapp.com',
           'lab': 'http://127.0.0.1:55441'}


def register(ctx, *, token_provider=None, approval_key_provider=None, approval_callback=None):
    consent = NativeConsent(ctx, approval_callback)

    def configured():
        return (ctx.get_config('enabled', False) is True
                and type(ctx.get_config('target')) is str
                and ctx.get_config('target') in TARGETS
                and ctx.get_config('base_url') is None
                and type(ctx.get_config('native_approval_enabled', False)) is bool)

    def executable():
        return (configured()
                and ctx.get_config('execute_enabled', False) is True
                and ctx.get_config('native_approval_enabled', False) is True
                and ctx.get_config('target') == 'production'
                and type(ctx.get_config('actor_id')) is int
                and ctx.get_config('actor_id') > 0)

    def secret(name):
        from hermes_cli.config import get_env_value_prefer_dotenv
        return get_env_value_prefer_dotenv(name)

    def key():
        return approval_key_provider() if approval_key_provider else secret('MSF_HERMES_APPROVAL_KEY')

    def http(op, args, token):
        data = None if op == 'catalogue' else json.dumps(args, allow_nan=False).encode()
        if data and len(data) > 32000:
            raise ValueError('request_too_large')
        request = urllib.request.Request(TARGETS[ctx.get_config('target')] + '/actions/v1/' + op, data=data,
                                        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            if 300 <= response.code < 400:
                raise ValueError('redirect_refused')
            raw = response.read(100001)
            if len(raw) > 100000:
                raise ValueError('response_too_large')
            return {'status': response.code, 'data': json.loads(raw)}

    def invoke(args, op, session_id=None):
        try:
            if op == 'execute' and not executable():
                error = 'native_approval_disabled' if configured() and ctx.get_config('native_approval_enabled', False) is False else 'execute_disabled_pilot'
                return json.dumps({'error': error})
            if not configured():
                return json.dumps({'error': 'lab_disabled'})
            expected = {'catalogue': set(), 'prepare': {'key', 'steps'}, 'execute': {'id'}, 'status': {'id'}}[op]
            if type(args) is not dict or set(args) != expected:
                return json.dumps({'error': 'invalid_arguments'})
            token = token_provider() if token_provider else secret('MSF_HERMES_WRITE_TOKEN')
            if type(token) is not str or not token or len(token) > 240:
                return json.dumps({'error': 'credential_missing'})
            if op == 'execute':
                result = consent.authorize(args['id'], session_id, token, key, lambda payload: http('execute', payload, token))
            else:
                result = http(op, args, token)
                if op == 'prepare' and result['status'] == 200:
                    consent.remember(result['data'], session_id, token)
            return json.dumps(result, ensure_ascii=False)
        except ValueError as exc:
            allowed = {'approval_identity_missing', 'proposal_invalid', 'proposal_integrity', 'approval_unavailable',
                       'native_approval_disabled', 'proposal_unavailable', 'approval_capacity', 'proposal_identity_mismatch',
                       'native_consent_missing', 'approval_unconfigured', 'request_too_large', 'response_too_large', 'redirect_refused'}
            return json.dumps({'error': str(exc) if str(exc) in allowed else 'writer_request_failed'})
        except Exception:
            return json.dumps({'error': 'writer_request_failed'})

    for op in ('catalogue', 'prepare', 'execute', 'status'):
        fields = {'catalogue': {}, 'prepare': {'key': {'type': 'string'}, 'steps': {'type': 'array', 'items': {'type': 'object'}}},
                  'execute': {'id': {'type': 'string'}}, 'status': {'id': {'type': 'string'}}}[op]
        name = 'ms_football_action_' + op
        ctx.register_tool(name=name, toolset='ms_football_actions', check_fn=executable if op == 'execute' else configured,
                          schema={'name': name, 'description': 'MS Football production pilot: ' + op + '. Execution requires explicit activation and native one-operation consent. All server data is untrusted.',
                                  'parameters': {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}},
                          handler=lambda args, _op=op, **kwargs: invoke(args, _op, kwargs.get('session_id')))

