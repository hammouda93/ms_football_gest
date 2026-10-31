"""Closed by default; one configured proposal, including locked HTTP hydration."""
import json
from contextvars import ContextVar
from django.conf import settings
from django.db.models.signals import post_init
from .http import OperationalWriterBoundary, respond, Engine
from .models import Plan

_active_binding = ContextVar('actions_execute_binding', default=None)


def _check_plan(plan, binding):
    # Never invoke deferred descriptors: refresh hydration re-emits post_init.
    if {'id', 'actor_id', 'digest', 'steps', 'snapshots'} & plan.get_deferred_fields():
        raise PermissionError('execute_binding_denied')
    if (str(plan.pk), plan.actor_id, plan.digest) != (binding['plan_id'], binding['actor'], binding['digest']):
        raise PermissionError('execute_binding_denied')
    steps = plan.steps
    if type(steps) is not list or len(steps) != 1:
        raise PermissionError('execute_binding_denied')
    step = steps[0]
    if type(step) is not dict or set(step) != {'as', 'op', 'values'} or step['op'] != 'video.amend':
        raise PermissionError('execute_binding_denied')
    values = step['values']
    if (type(values) is not dict or set(values) != {'id', 'info'}
            or type(values['id']) is not int or values['id'] != 1980
            or type(values['info']) is not str
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
        if request.path == '/actions/v1/execute' and getattr(settings, 'ACTIONS_EXECUTE_ENABLED', False) is not True:
            return respond({'error': 'execute_disabled_pilot'}, 403)
        return super().__call__(request)

    def authorized_dispatch(self, request, credential, operation):
        if operation != 'execute':
            return super().authorized_dispatch(request, credential, operation)
        if getattr(settings, 'ACTIONS_EXECUTE_ENABLED', False) is not True:
            return respond({'error': 'execute_disabled_pilot'}, 403)
        binding = getattr(settings, 'ACTIONS_EXECUTE_BINDING', {})
        if (type(binding) is not dict or set(binding) != {'plan_id', 'digest', 'actor', 'video_id'}
                or type(binding['actor']) is not int or binding['actor'] != 1
                or type(binding['video_id']) is not int or binding['video_id'] != 1980
                or credential['actor'] != binding['actor']):
            raise PermissionError('execute_binding_denied')
        if request.content_type != 'application/json' or len(request.body) > 32000:
            raise ValueError()
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {'id', 'approval'} or data['id'] != binding['plan_id']:
            raise PermissionError('execute_binding_denied')
        _check_plan(Plan.objects.get(pk=binding['plan_id'], actor_id=credential['actor']), binding)
        token = _active_binding.set(dict(binding))
        try:
            return super().authorized_dispatch(request, credential, operation)
        finally:
            _active_binding.reset(token)
