"""Bounded native Hermes actions for the production workspace.

Only existing Django model forms and explicit business columns are accepted.
No upload, external notification, payment capture, or worker claim is triggered.
"""
import hashlib
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict
from django.utils import timezone

from gestion_joueurs.forms import VideoForm
from gestion_joueurs.models import Video
from client_portal.forms import (
    VideoActivityForm, VideoVersionForm, RevisionResolutionForm, PaymentRequestForm,
)
from client_portal.models import VideoActivity, VideoVersion, RevisionRequest, PaymentRequest


def scalar(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, default=str, separators=(",", ":")
    ).encode()).hexdigest()


class ProductionBase:
    model = Video
    operation = ""

    @staticmethod
    def actor(actor_id):
        try:
            return get_user_model().objects.get(
                pk=actor_id, is_active=True, is_superuser=True,
            )
        except get_user_model().DoesNotExist:
            raise PermissionError("permission_denied") from None

    def video(self, pk, actor_id, lock=False):
        self.actor(actor_id)
        qs = Video.objects.select_for_update() if lock else Video.objects
        try:
            return qs.get(pk=pk)
        except Video.DoesNotExist:
            raise ValueError("video_missing") from None

    def snapshot(self, values, actor_id, lock=False):
        video_id = values.get("video", values.get("id"))
        self.video(video_id, actor_id, lock)
        q = Video.objects.filter(pk=video_id)
        if lock:
            q = q.select_for_update()
        return digest({"video": list(q.values())})


class VideoProductionSettings(ProductionBase):
    operation = "video.production.amend"
    model = Video
    fields = ("matches_processed", "seasons_to_process", "client_portal_visible")

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["id", *self.fields],
            "required": ["id"],
            "schema": {
                "id": {"type": "integer"},
                "matches_processed": {"type": "integer"},
                "seasons_to_process": {"type": "integer", "enum": [1, 2]},
                "client_portal_visible": {"type": "boolean"},
            },
            "family": "video_production_settings/v1",
            "permission": "active_superuser",
            "sourceForm": "gestion_joueurs.forms.VideoForm",
            "effects": ["selected_video_columns_only"],
            "excludedEffects": [
                "status", "delivery", "publication", "jobs", "emails",
                "payments", "account_provisioning", "video_upload",
            ],
        }

    def target(self, pk, actor_id, lock=False):
        return self.video(pk, actor_id, lock)

    def cleaned(self, values, actor_id, lock=False):
        video = self.target(values["id"], actor_id, lock)
        chosen = set(values) - {"id"}
        if not chosen:
            raise ValueError("empty_amendment")
        if chosen - set(self.fields):
            raise ValueError("field_forbidden")
        data = model_to_dict(video)
        data.update({k: values[k] for k in chosen})
        form = VideoForm(data, instance=video, user=self.actor(actor_id))
        if not form.is_valid():
            raise ValueError("invalid_video_form")
        changes = {k: form.cleaned_data[k] for k in chosen}
        if "matches_processed" in changes and changes["matches_processed"] is None:
            raise ValueError("invalid_progress")
        return video, changes

    def preview(self, step, actor_id):
        video, changes = self.cleaned(step["values"], actor_id)
        return scalar({
            "as": step["as"], "op": step["op"], "id": video.pk,
            "old": {k: getattr(video, k) for k in changes},
            "new": changes, "contract": self.contract(),
        })

    def apply(self, values, actor_id):
        video, changes = self.cleaned(values, actor_id, lock=True)
        for name, value in changes.items():
            setattr(video, name, value)
        video.save(update_fields=sorted(changes))
        return video


class VideoActivityAdd(ProductionBase):
    operation = "video.activity.add"
    model = VideoActivity

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["video", "message", "visibility"],
            "required": ["video", "message", "visibility"],
            "schema": {
                "video": {"type": "integer"},
                "message": {"type": "string", "maxLength": 4000},
                "visibility": {
                    "type": "string", "enum": ["internal", "client"],
                },
            },
            "family": "video_activity/v1",
            "sourceForm": "client_portal.forms.VideoActivityForm",
            "permission": "active_superuser",
            "effects": ["video_note_record"],
            "excludedEffects": [
                "email", "whatsapp", "notification_send", "video_status",
                "publication", "jobs",
            ],
        }

    def cleaned(self, values, actor_id, lock=False):
        video = self.video(values["video"], actor_id, lock)
        if set(values) != {"video", "message", "visibility"}:
            raise ValueError("field_forbidden")
        if not values["message"].strip() or len(values["message"]) > 4000:
            raise ValueError("invalid_message")
        form = VideoActivityForm({
            "message": values["message"],
            "visibility": values["visibility"],
        })
        if not form.is_valid():
            raise ValueError("invalid_activity_form")
        return video, form.cleaned_data

    def preview(self, step, actor_id):
        video, changes = self.cleaned(step["values"], actor_id)
        return scalar({
            "as": step["as"], "op": step["op"],
            "id": None, "old": None,
            "new": {
                "video_id": video.pk,
                "kind": VideoActivity.Kind.NOTE,
                "visibility": changes["visibility"],
                "message": changes["message"],
                "metadata": {},
                "created_by_id": actor_id,
            },
            "generated": ["id", "created_at"],
            "contract": self.contract(),
        })

    def apply(self, values, actor_id):
        video, changes = self.cleaned(values, actor_id, lock=True)
        return VideoActivity.objects.create(
            video=video, kind=VideoActivity.Kind.NOTE,
            message=changes["message"], visibility=changes["visibility"],
            created_by_id=actor_id,
        )


PRODUCTION = {
    "video.production.amend": VideoProductionSettings(),
    "video.activity.add": VideoActivityAdd(),
}
