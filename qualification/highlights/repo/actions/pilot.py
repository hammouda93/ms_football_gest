"""Closed by default; one configured proposal, including locked HTTP hydration."""
import json
from contextvars import ContextVar
from django.conf import settings
from django.db.models.signals import post_init
from .http import OperationalWriterBoundary, respond, Engine
from .models import Plan
from .mount import valid_binding, _configuration, APPROVED_OPERATIONS

_active_binding = ContextVar('actions_execute_binding', default=None)


def _check_plan(plan, binding):
    # Never invoke deferred descriptors: refresh hydration re-emits post_init.
    if {'id', 'actor_id', 'digest', 'steps', 'snapshots'} & plan.get_deferred_fields():
        raise PermissionError('execute_binding_denied')
    if not valid_binding(binding):
        raise PermissionError('execute_binding_denied')
    if binding.get('mode') == 'service':
        if (plan.actor_id != binding['actor'] or type(plan.steps) is not list
                or not 1 <= len(plan.steps) <= 12
                or any(type(s) is not dict or s.get('op') not in binding['operations'] for s in plan.steps)
                or Engine.proposal_digest(plan.steps, plan.snapshots) != plan.digest):
            raise PermissionError('execute_binding_denied')
        return
    if (str(plan.pk), plan.actor_id, plan.digest) != (binding['plan_id'], binding['actor'], binding['digest']):
        raise PermissionError('execute_binding_denied')
    steps = plan.steps
    if (not valid_binding(binding) or type(steps) is not list
            or [s.get('op') if type(s) is dict else None for s in steps] != binding['operations']
            or Engine.proposal_digest(steps, plan.snapshots) != binding['digest']):
        raise PermissionError('execute_binding_denied')


def _guard_hydrated_plan(sender, instance, **kwargs):
    # HTTP's SELECT FOR UPDATE acquires its row lock before hydration.
    binding = _active_binding.get()
    if binding is not None:
        _check_plan(instance, binding)


post_init.connect(_guard_hydrated_plan, sender=Plan, weak=False,
                  dispatch_uid='actions.pilot.single_plan_locked_guard')


class PrepareOnlyBoundary(OperationalWriterBoundary):
    def __call__(self, request):
        if request.path == '/actions/v1/execute' and (
                getattr(settings, 'ACTIONS_EXECUTE_ENABLED', False) is not True
                or not valid_binding(getattr(settings, 'ACTIONS_EXECUTE_BINDING', {}))
                or not isinstance(getattr(settings, 'ACTIONS_APPROVAL_KEY', ''), str)
                or len(getattr(settings, 'ACTIONS_APPROVAL_KEY', '')) < 32):
            return respond({'error': 'execute_disabled_pilot'}, 403)
        if request.path == '/actions' or request.path.startswith('/actions/'):
            try:
                config = _configuration(json.dumps({'enabled':getattr(settings, 'ACTIONS_ENABLED', False),
                    'credentials':getattr(settings, 'ACTIONS_CREDENTIALS', {})}))
                from .registry import catalogue
                reader_hashes = {c['token_hash'] for c in getattr(settings, 'DATA_ACCESS_CREDENTIALS', [])}
                if (not config['enabled'] or set(catalogue()) != APPROVED_OPERATIONS
                        or reader_hashes & set(config['credentials'])):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, AttributeError):
                return respond({'error': 'writer_disabled'}, 403)
        return super().__call__(request)

    def authorized_dispatch(self, request, credential, operation):
        if operation != 'execute':
            return super().authorized_dispatch(request, credential, operation)
        if getattr(settings, 'ACTIONS_EXECUTE_ENABLED', False) is not True:
            return respond({'error': 'execute_disabled_pilot'}, 403)
        binding = getattr(settings, 'ACTIONS_EXECUTE_BINDING', {})
        if (not valid_binding(binding) or credential['actor'] != binding['actor']
                or any('op:' + op not in credential['scopes'] for op in binding['operations'])):
            raise PermissionError('execute_binding_denied')
        if request.content_type != 'application/json' or len(request.body) > 32000:
            raise ValueError()
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {'id', 'approval'}:
            raise PermissionError('execute_binding_denied')
        if binding.get('mode') == 'service':
            import uuid
            if type(data['id']) is not str or str(uuid.UUID(data['id'])) != data['id']:
                raise ValueError('invalid_request')
            plan_id = data['id']
        else:
            if data['id'] != binding['plan_id']:
                raise PermissionError('execute_binding_denied')
            plan_id = binding['plan_id']
        _check_plan(Plan.objects.get(pk=plan_id, actor_id=credential['actor']), binding)
        token = _active_binding.set(dict(binding))
        try:
            return super().authorized_dispatch(request, credential, operation)
        finally:
            _active_binding.reset(token)
