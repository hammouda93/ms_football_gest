"""Nonmutating host approval connectivity diagnostic. No execution capability."""
import json
import secrets
import threading
import time

EVENTS = ('on_human_input_request', 'pre_approval_request', 'post_approval_response', 'on_human_input_resolved')

class ApprovalProbe:
    def __init__(self, ctx):
        self.lock = threading.RLock()
        self.pending = None
        self.closed = False
        for event in EVENTS:
            ctx.register_hook(event, lambda _event=event, **kw: self.observe(_event, kw))
        ctx.on_unload(self.close)

    def close(self):
        with self.lock:
            self.closed = True
            if self.pending is not None:
                self.pending['bad'] = True

    def observe(self, event, kw):
        with self.lock:
            p = self.pending
            if p is None:
                return
            human = event.startswith('on_human')
            target = kw.get('prompt') if human else kw.get('command')
            if target != p['command'] and kw.get('pattern_key') != p['pattern']:
                return
            if kw.get('session_id') != p['session'] or kw.get('session_key') != p['route']:
                p['bad'] = True
            if event != EVENTS[len(p['events'])] if len(p['events']) < 4 else True:
                p['bad'] = True
            p['events'].append(event)
            if human:
                if kw.get('kind') != 'approval' or target != p['command'] or not kw.get('request_id'):
                    p['bad'] = True
                if event == 'on_human_input_request':
                    p['human_id'] = kw.get('request_id')
                elif kw.get('request_id') != p.get('human_id') or kw.get('outcome') != 'once':
                    p['bad'] = True
            else:
                if (target != p['command'] or kw.get('pattern_key') != p['pattern']
                        or kw.get('pattern_keys') != [p['pattern']] or kw.get('description') != p['reason']
                        or kw.get('surface') not in ('cli', 'gateway') or kw.get('coalesced')
                        or kw.get('cancelled') or kw.get('decided_by')):
                    p['bad'] = True
                if event == 'pre_approval_request':
                    p['surface'] = kw.get('surface')
                elif kw.get('surface') != p.get('surface') or kw.get('choice') != 'once':
                    p['bad'] = True

    def invoke(self, args, session_id=None):
        from tools.approval import request_tool_approval, is_approval_bypass_active, is_approved
        from tools.approval_context import get_current_session_key
        from tools.interrupt import is_interrupted
        if type(args) is not dict or args:
            raise ValueError('invalid_arguments')
        route = get_current_session_key(default='')
        if type(session_id) is not str or not session_id or type(route) is not str or not route or route == 'default':
            raise ValueError('host_identity_missing')
        nonce = secrets.token_hex(24)
        tool = 'ms_football_approval_probe_' + nonce
        rule = 'msf-probe-' + nonce
        pattern = 'plugin_rule:' + rule
        reason = 'Diagnostic nonmutant uniquement. Choisir UNE FOIS / once. Aucune autorisation de production. Nonce: ' + nonce
        p = dict(session=session_id, route=route, command='<' + tool + '> (plugin approval rule)', pattern=pattern, reason=reason, events=[], bad=False)
        with self.lock:
            if self.closed or self.pending is not None or is_interrupted() or is_approval_bypass_active() or is_approved(route, pattern):
                raise ValueError('probe_unavailable')
            self.pending = p
        deadline = time.monotonic() + 120
        try:
            decision = request_tool_approval(tool, reason, rule_key=rule, approval_callback=None)
            with self.lock:
                if (not isinstance(decision, dict) or decision.get('approved') is not True or p['bad']
                        or p['events'] != list(EVENTS) or not p.get('human_id') or self.closed
                        or time.monotonic() >= deadline or is_interrupted() or is_approval_bypass_active()
                        or is_approved(route, pattern) or get_current_session_key(default='') != route):
                    raise ValueError('native_once_not_verified')
                return {'receipt': {'nonce': nonce, 'session_id': session_id, 'session_key': route,
                                    'request_id': p['human_id'], 'choice': 'once', 'event_count': 4,
                                    'execution_authorized': False}}
        finally:
            with self.lock:
                self.pending = None

def register(ctx):
    probe = ApprovalProbe(ctx)
    def handler(args, **kwargs):
        try:
            return json.dumps(probe.invoke(args, kwargs.get('session_id')))
        except ValueError as exc:
            return json.dumps({'error': str(exc) if str(exc) in {'invalid_arguments', 'host_identity_missing', 'probe_unavailable', 'native_once_not_verified'} else 'probe_failed'})
        except Exception:
            return json.dumps({'error': 'probe_failed'})
    ctx.register_tool(name='ms_football_approval_probe', toolset='ms_football_approval_probe',
                      check_fn=lambda: not probe.closed, handler=handler,
                      schema={'name': 'ms_football_approval_probe',
                              'description': 'Nonmutating native host approval connectivity diagnostic. Requires human UNE FOIS / once; receipt never authorizes production.',
                              'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}})
