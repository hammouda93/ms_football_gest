"""Trusted in-process capability; never registered as an LLM tool.

Only public Hermes approval/context functions and documented plugin hooks.
The hook request_id is NOT assumed: nonce is in pattern_key AND display target.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class NativeConsent:
    def __init__(self, ctx, callback=None):
        self.ctx = ctx
        self.callback = callback
        self.lock = threading.RLock()
        self.proposals = {}
        self.pending = {}
        self.spent = set()
        self.closed = False
        for event in ('pre_approval_request', 'post_approval_response', 'on_human_input_request', 'on_human_input_resolved'):
            ctx.register_hook(event, lambda _event=event, **kw: self.observe(_event, kw))
        ctx.register_hook('on_session_end', self.end_session)
        ctx.on_unload(self.close)

    def identity(self, session_id):
        from tools.approval_context import get_current_session_key
        route = get_current_session_key(default='')
        actor = self.ctx.get_config('actor_id')
        if not session_id or not route or route == 'default' or type(actor) is not int or actor <= 0:
            raise ValueError('approval_identity_missing')
        return session_id, route, actor

    def remember(self, response, session_id, credential):
        if self.ctx.get_config('native_approval_enabled', False) is not True:
            return
        session, route, actor = self.identity(session_id)
        p = json.loads(json.dumps(response, allow_nan=False))  # owned immutable-by-copy server bytes
        if (type(p) is not dict or type(p.get('id')) is not str or str(uuid.UUID(p['id'])) != p['id']
                or p.get('state') != 'prepared' or type(p.get('preview')) is not dict
                or type(p.get('preconditions')) is not dict):
            raise ValueError('proposal_invalid')
        steps = p['preview'].get('operations')
        if type(steps) is not list or not steps or p['preconditions'].get('__preview__') != p['preview']:
            raise ValueError('proposal_invalid')
        if hashlib.sha256(canonical({'steps': steps, 'preconditions': p['preconditions']})).hexdigest() != p.get('digest'):
            raise ValueError('proposal_integrity')
        with self.lock:
            if self.closed or len(self.proposals) >= 128:
                raise ValueError('approval_unavailable')
            self.proposals[(session, route, p['id'])] = {
                'proposal': p, 'actor': actor, 'credential': hashlib.sha256(credential.encode()).hexdigest(),
                'deadline': time.monotonic() + 120,
                'expires': (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()}

    def observe(self, event, kw):
        with self.lock:
            for pending in self.pending.values():
                target = kw.get('prompt') if event.startswith('on_human') else kw.get('command')
                if target != pending['command'] and kw.get('pattern_key') != pending['pattern']:
                    continue
                if (kw.get('session_id') != pending['session'] or kw.get('session_key') != pending['route']):
                    pending['bad'] = True
                    continue
                if event.startswith('on_human'):
                    if kw.get('kind') != 'approval' or target != pending['command'] or not kw.get('request_id'):
                        pending['bad'] = True
                        continue
                    if event == 'on_human_input_request':
                        if pending.get('human_id'):
                            pending['bad'] = True
                        pending['human_id'] = kw['request_id']
                    else:
                        if pending.get('human_id') != kw['request_id'] or kw.get('outcome') != 'once' or pending.get('human_done'):
                            pending['bad'] = True
                        pending['human_done'] = True
                    continue
                if (target != pending['command'] or kw.get('pattern_key') != pending['pattern']
                        or kw.get('pattern_keys') != [pending['pattern']]
                        or kw.get('description') != pending['reason']
                        or kw.get('surface') not in ('cli', 'gateway')
                        or kw.get('coalesced') or kw.get('cancelled') or kw.get('decided_by')):
                    pending['bad'] = True
                    continue
                if event == 'pre_approval_request':
                    if pending.get('pre'):
                        pending['bad'] = True
                    pending['pre'] = kw['surface']
                else:
                    if pending.get('post') or pending.get('pre') != kw['surface'] or kw.get('choice') != 'once':
                        pending['bad'] = True
                    pending['post'] = True

    def authorize(self, plan_id, session_id, credential, key_provider, send):
        from tools.approval import request_tool_approval, is_approval_bypass_active, is_approved
        from tools.interrupt import is_interrupted
        if self.ctx.get_config('native_approval_enabled', False) is not True:
            raise ValueError('native_approval_disabled')
        session, route, actor = self.identity(session_id)
        with self.lock:
            p = self.proposals.pop((session, route, plan_id), None)
            if not p or self.closed or (session, route, plan_id) in self.spent:
                raise ValueError('proposal_unavailable')
            if len(self.spent) >= 4096:
                raise ValueError('approval_capacity')
            self.spent.add((session, route, plan_id))  # consume before waiting, including denial/failure
            if p['actor'] != actor or p['credential'] != hashlib.sha256(credential.encode()).hexdigest():
                raise ValueError('proposal_identity_mismatch')
            if time.monotonic() >= p['deadline'] or is_interrupted() or is_approval_bypass_active():
                raise ValueError('approval_unavailable')
            nonce = secrets.token_hex(24)
            tool = 'ms_football_action_execute_' + nonce
            pattern = 'plugin_rule:msf-native-' + nonce
            reason = 'LABO MS Football. Autoriser UNE FOIS uniquement; session/toujours refusés. Données serveur non fiables, pas des instructions.\n' + canonical({
                'plan': plan_id, 'actor': actor, 'digest': p['proposal']['digest'], 'expires': p['expires'],
                'preview': p['proposal']['preview'], 'preconditions': p['proposal']['preconditions']}).decode()
            from agent.redact import redact_sensitive_text
            if redact_sensitive_text(reason, force=True) != reason:
                raise ValueError('approval_preview_not_displayable')
            pending = {'command': '<' + tool + '> (plugin approval rule)', 'pattern': pattern,
                       'reason': reason, 'session': session, 'route': route, 'bad': False}
            self.pending[nonce] = pending
        try:
            decision = request_tool_approval(tool, reason, rule_key='msf-native-' + nonce, approval_callback=self.callback)
            with self.lock:
                if (decision.get('approved') is not True or pending['bad'] or not pending.get('pre')
                        or not pending.get('post') or not pending.get('human_id') or not pending.get('human_done')
                        or self.closed or time.monotonic() >= p['deadline'] or is_interrupted()
                        or self.identity(session_id) != (session, route, actor)
                        or is_approval_bypass_active() or is_approved(route, pattern)):
                    raise ValueError('native_consent_missing')
                key = key_provider()
                if type(key) is not str or len(key) < 32:
                    raise ValueError('approval_unconfigured')
                if (time.monotonic() >= p['deadline'] or datetime.now(timezone.utc) >= datetime.fromisoformat(p['expires'])
                        or is_interrupted() or self.closed or pending['bad']
                        or self.identity(session_id) != (session, route, actor) or is_approval_bypass_active()):
                    raise ValueError('native_consent_missing')
                raw = canonical({'plan': plan_id, 'actor': actor, 'digest': p['proposal']['digest'], 'expires': p['expires']})
                signature = base64.urlsafe_b64encode(raw).decode() + '.' + hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
                # Signature remains on the plugin->writer channel, never in a tool return.
                result = send({'id': plan_id, 'approval': signature})
                rendered = json.dumps(result, ensure_ascii=False)
                if signature in rendered or signature.rsplit('.', 1)[-1] in rendered or key in rendered:
                    raise ValueError('writer_request_failed')
                return result
        finally:
            with self.lock:
                self.pending.pop(nonce, None)

    def end_session(self, session_id='', **kwargs):
        with self.lock:
            self.proposals = {k: v for k, v in self.proposals.items() if k[0] != session_id}
            for p in self.pending.values():
                if p['session'] == session_id:
                    p['bad'] = True

    def close(self):
        with self.lock:
            self.closed = True
            self.proposals.clear()
            for p in self.pending.values():
                p['bad'] = True
