"""Reviewed internal delivery registration; link is optional, no send/upload."""
from urllib.parse import urlsplit, unquote
import re

from django.utils import timezone
from .workflow import ProductionTransition, external_effects_closed
from client_portal.forms import ProductionVideoStatusForm
from client_portal.services import invoice_snapshot


def public_path(path):
    """Keep strict checks for newly supplied final links (not for blank links)."""
    if re.search(r'%(?![0-9A-Fa-f]{2})', path):
        raise ValueError('public_final_link_required')
    try:
        decoded = unquote(path, encoding='utf-8', errors='strict')
    except UnicodeError:
        raise ValueError('public_final_link_required') from None
    if '%' in decoded:
        raise ValueError('public_final_link_required')
    for value in (path, decoded):
        if (
            any(ord(c) < 33 or ord(c) == 127 for c in value)
            or any(c in value for c in '\\?#;')
            or '//' in value
            or any(s in ('.', '..', 'access') for s in value.split('/'))
        ):
            raise ValueError('public_final_link_required')


class InternalDelivery(ProductionTransition):
    def __init__(self):
        super().__init__('status')

    def contract(self):
        return {
            'model': 'gestion_joueurs.Video',
            'fields': ['id', 'video_link'],
            'required': ['id'],
            'schema': {
                'id': {'type': 'integer'},
                'video_link': {'type': 'string', 'format': 'uri', 'required': False},
            },
            'family': 'internal_delivery/v1',
            'sourceForm': 'client_portal.forms.ProductionVideoStatusForm',
            'permission': 'active_superuser',
            'effects': [
                'status_history', 'delivery_date_if_missing',
                'workflow_sync', 'stage_activity',
            ],
            'excludedEffects': [
                'send', 'upload', 'publication', 'portal_visibility_change',
                'access_generation', 'jobs',
            ],
            'composition': 'single_step_only',
            'linkOptional': True,
            'result': 'internal delivered status, not proof of a sent file',
        }

    @staticmethod
    def persisted_link(video, cleaned_link):
        """Match the existing production view's blank / nullable URL behavior."""
        submitted = (cleaned_link or '').strip()
        return submitted if submitted != (video.video_link or '') else video.video_link

    def cleaned(self, values, actor_id, lock=False):
        if set(values) - {'id', 'video_link'} or 'id' not in values:
            raise ValueError('field_forbidden')
        actor = self.actor(actor_id)
        if not actor.is_superuser:
            raise PermissionError('permission_denied')
        obj = self.target(values['id'], actor_id, lock)
        self.dependencies(obj, lock)
        if obj.status == 'delivered':
            raise ValueError('already_delivered')

        # No link supplied: keep an existing URL, if any. Explicit '' clears it.
        link_supplied = 'video_link' in values
        link = values['video_link'] if link_supplied else (obj.video_link or '')
        if type(link) is not str:
            raise ValueError('invalid_delivery_link')

        # Validate new public links; never force a URL or expose signed tokens.
        if link and link_supplied:
            if any(ord(c) < 33 or ord(c) == 127 for c in link):
                raise ValueError('public_final_link_required')
            u = urlsplit(link)
            if (
                u.scheme != 'https' or not u.hostname
                or u.username is not None or u.password is not None
                or u.query or u.fragment
            ):
                raise ValueError('public_final_link_required')
            public_path(u.path)

        form = ProductionVideoStatusForm(
            {'status': 'delivered', 'video_link': link},
            user=actor, video=obj,
        )
        if not form.is_valid():
            raise ValueError('invalid_delivery_form')
        return obj, form.cleaned_data

    def preview(self, step, actor_id, projected_players=None):
        preview = super().preview(step, actor_id, projected_players)
        video, clean = self.cleaned(step['values'], actor_id)
        payment = invoice_snapshot(video)
        final_url = self.persisted_link(video, clean['video_link'])
        preview['history'][0]['comment'] = 'Video Delivered.'
        preview['videoChanges'] = {
            'video_link': final_url,
            'delivery_date': (
                video.delivery_date or timezone.localdate()
            ).isoformat(),
        }
        preview['portal'] = {
            'visible_before': video.client_portal_visible,
            'visible_after': video.client_portal_visible,
            'balance': str(payment.balance),
            'final_link_present_after': bool(final_url),
            'final_available_after': bool(final_url) and payment.balance <= 0,
            'access_rights_unchanged': True,
            'sent': False,
            'uploaded': False,
        }
        return preview

    def apply(self, values, actor_id):
        from client_portal.views import production_video_status_update
        from .view_adapter import request_for

        obj, clean = self.cleaned(values, actor_id, lock=True)
        expected_link = self.persisted_link(obj, clean['video_link'])
        with external_effects_closed():
            response = production_video_status_update(
                request_for(actor_id, dict(clean, notification_action='none')),
                obj.pk,
            )
        if response.status_code != 302:
            raise ValueError('delivery_view_failed')
        obj.refresh_from_db()
        if obj.status != 'delivered' or obj.video_link != expected_link:
            raise ValueError('delivery_not_persisted')
        return obj


DELIVERY = {'video.delivery.internal': InternalDelivery()}
