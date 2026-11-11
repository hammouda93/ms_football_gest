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



class VideoVersionAdd(ProductionBase):
    operation = "video.version.add"
    model = VideoVersion

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["video", "title", "preview_url", "final_url", "notes"],
            "required": ["video", "preview_url"],
            "schema": {
                "video": {"type": "integer"},
                "title": {"type": "string", "maxLength": 160},
                "preview_url": {"type": "string", "format": "uri"},
                "final_url": {"type": "string", "format": "uri"},
                "notes": {"type": "string", "maxLength": 4000},
            },
            "family": "video_version/v1",
            "sourceForm": "client_portal.forms.VideoVersionForm",
            "permission": "active_superuser",
            "effects": [
                "version_created", "pending_versions_replaced",
                "client_visible_activity_record",
            ],
            "excludedEffects": [
                "publication", "external_send", "youtube_upload",
                "video_status", "invoice", "jobs",
            ],
            "composition": "single_step_only",
        }

    def versions(self, video_id, lock=False):
        q = VideoVersion.objects.filter(video_id=video_id).order_by("pk")
        if lock:
            q = q.select_for_update()
        versions = list(q[:257])
        if len(versions) > 256:
            raise ValueError("version_limit")
        return versions

    def cleaned(self, values, actor_id, lock=False):
        self.video(values["video"], actor_id, lock)
        if set(values) - set(self.contract()["fields"]):
            raise ValueError("field_forbidden")
        form = VideoVersionForm({
            "title": values.get("title", ""),
            "preview_url": values["preview_url"],
            "final_url": values.get("final_url", ""),
            "notes": values.get("notes", ""),
        })
        if not form.is_valid():
            raise ValueError("invalid_version_form")
        versions = self.versions(values["video"], lock)
        number = max((x.version_number for x in versions), default=0) + 1
        if number > 32767:
            raise ValueError("version_limit")
        return form.cleaned_data, number, [
            x.pk for x in versions if x.status == VideoVersion.Status.PENDING
        ]

    def snapshot(self, values, actor_id, lock=False):
        original = super().snapshot(values, actor_id, lock)
        versions = self.versions(values["video"], lock)
        return digest({
            "base": original,
            "versions": [
                scalar({f.attname: getattr(v, f.attname) for f in v._meta.concrete_fields})
                for v in versions
            ],
        })

    def preview(self, step, actor_id):
        changes, number, previous = self.cleaned(step["values"], actor_id)
        return scalar({
            "as": step["as"], "op": step["op"],
            "id": None, "old": None,
            "new": {
                "video_id": step["values"]["video"],
                "version_number": number,
                "title": changes["title"],
                "preview_url": changes["preview_url"],
                "final_url": changes["final_url"],
                "notes": changes["notes"],
                "status": VideoVersion.Status.PENDING,
                "uploaded_by_id": actor_id,
                "approved_by_id": None,
                "approved_at": None,
            },
            "replaced_ids": previous,
            "generated": ["id", "created_at"],
            "contract": self.contract(),
        })

    def apply(self, values, actor_id):
        changes, number, previous = self.cleaned(values, actor_id, lock=True)
        if previous:
            VideoVersion.objects.filter(
                pk__in=previous,
                video_id=values["video"],
                status=VideoVersion.Status.PENDING,
            ).update(status=VideoVersion.Status.REPLACED)
        version = VideoVersion.objects.create(
            video_id=values["video"], version_number=number,
            title=changes["title"], preview_url=changes["preview_url"],
            final_url=changes["final_url"], notes=changes["notes"],
            status=VideoVersion.Status.PENDING,
            uploaded_by_id=actor_id,
        )
        VideoActivity.objects.create(
            video_id=values["video"], kind=VideoActivity.Kind.VERSION,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"La version {number} est disponible pour validation.",
            created_by_id=actor_id,
        )
        return version


class VideoPaymentRequestAdd(ProductionBase):
    operation = "video.payment_request.add"
    model = PaymentRequest

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["video", "label", "amount", "due_date", "payment_url"],
            "required": ["video", "label", "amount"],
            "schema": {
                "video": {"type": "integer"},
                "label": {"type": "string", "maxLength": 120},
                "amount": {"type": "string"},
                "due_date": {"type": "string", "format": "date"},
                "payment_url": {"type": "string", "format": "uri"},
            },
            "family": "video_payment_request/v1",
            "sourceForm": "client_portal.forms.PaymentRequestForm",
            "permission": "active_superuser",
            "effects": ["payment_request_created", "client_visible_activity_record"],
            "excludedEffects": [
                "payment_capture", "bank_transfer", "provider_api_call",
                "email", "whatsapp", "invoice_settled", "jobs",
            ],
            "composition": "single_step_only",
        }

    def cleaned(self, values, actor_id, lock=False):
        from urllib.parse import urlsplit

        self.video(values["video"], actor_id, lock)
        if set(values) - set(self.contract()["fields"]):
            raise ValueError("field_forbidden")
        # No embedded credentials or query tokens may enter a sealed proposal.
        url = values.get("payment_url", "")
        if url:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password
                or parsed.query or parsed.fragment
            ):
                raise ValueError("public_payment_link_required")
        form = PaymentRequestForm({
            "label": values["label"],
            "amount": values["amount"],
            "due_date": values.get("due_date", ""),
            "payment_url": url,
        })
        if not form.is_valid():
            raise ValueError("invalid_payment_request_form")
        if form.cleaned_data["amount"] <= 0:
            raise ValueError("invalid_amount")
        return form.cleaned_data

    def preview(self, step, actor_id):
        values = step["values"]
        data = self.cleaned(values, actor_id)
        return scalar({
            "as": step["as"], "op": step["op"],
            "id": None, "old": None,
            "new": {
                "video_id": values["video"],
                "label": data["label"],
                "amount": data["amount"],
                "due_date": data["due_date"],
                "payment_url": data["payment_url"],
                "status": PaymentRequest.Status.PENDING,
                "created_by_id": actor_id,
            },
            "generated": ["id", "created_at", "updated_at"],
            "contract": self.contract(),
        })

    def apply(self, values, actor_id):
        data = self.cleaned(values, actor_id, lock=True)
        obj = PaymentRequest.objects.create(
            video_id=values["video"],
            label=data["label"], amount=data["amount"],
            due_date=data["due_date"], payment_url=data["payment_url"],
            status=PaymentRequest.Status.PENDING,
            created_by_id=actor_id,
        )
        VideoActivity.objects.create(
            video_id=values["video"], kind=VideoActivity.Kind.PAYMENT,
            visibility=VideoActivity.Visibility.CLIENT,
            message=(
                f"Une demande de paiement « {obj.label} » de "
                f"{obj.amount:.2f} est disponible."
            ),
            created_by_id=actor_id,
        )
        return obj



class VideoRevisionResolve(ProductionBase):
    operation = "video.revision.resolve"
    model = RevisionRequest

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["id", "status", "staff_response"],
            "required": ["id", "status"],
            "schema": {
                "id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "resolved", "rejected"],
                },
                "staff_response": {"type": "string", "maxLength": 4000},
            },
            "family": "video_revision/v1",
            "sourceForm": "client_portal.forms.RevisionResolutionForm",
            "permission": "active_superuser",
            "effects": [
                "revision_status_and_response",
                "client_visible_activity_record",
            ],
            "excludedEffects": [
                "email", "whatsapp", "version_approval",
                "publication", "jobs", "payment",
            ],
            "composition": "single_step_only",
        }

    def target(self, pk, actor_id, lock=False):
        self.actor(actor_id)
        q = RevisionRequest.objects.select_for_update() if lock else RevisionRequest.objects
        try:
            return q.select_related("version__video").get(pk=pk)
        except RevisionRequest.DoesNotExist:
            raise ValueError("revision_missing") from None

    def cleaned(self, values, actor_id, lock=False):
        revision = self.target(values["id"], actor_id, lock)
        if set(values) - set(self.contract()["fields"]):
            raise ValueError("field_forbidden")
        form = RevisionResolutionForm({
            "status": values["status"],
            "staff_response": values.get("staff_response", ""),
        })
        if not form.is_valid():
            raise ValueError("invalid_revision_form")
        return revision, form.cleaned_data

    def snapshot(self, values, actor_id, lock=False):
        revision = self.target(values["id"], actor_id, lock)
        q = RevisionRequest.objects.filter(pk=revision.pk)
        if lock:
            q = q.select_for_update()
        related_video = Video.objects.filter(pk=revision.version.video_id)
        if lock:
            related_video = related_video.select_for_update()
        return digest({
            "revision": list(q.values()),
            "video": list(related_video.values()),
        })

    def preview(self, step, actor_id):
        revision, data = self.cleaned(step["values"], actor_id)
        terminal = data["status"] in (
            RevisionRequest.Status.RESOLVED, RevisionRequest.Status.REJECTED,
        )
        return scalar({
            "as": step["as"], "op": step["op"],
            "id": revision.pk,
            "video_id": revision.version.video_id,
            "old": {
                "status": revision.status,
                "staff_response": revision.staff_response,
                "resolved_by_id": revision.resolved_by_id,
                "resolved_at": revision.resolved_at,
            },
            "new": {
                "status": data["status"],
                "staff_response": data["staff_response"],
                "resolved_by_id": actor_id if terminal else None,
                "resolved_at": "set_at_execution" if terminal else None,
            },
            "generated": ["resolved_at", "updated_at"],
            "contract": self.contract(),
        })

    def apply(self, values, actor_id):
        revision, data = self.cleaned(values, actor_id, lock=True)
        revision.status = data["status"]
        revision.staff_response = data["staff_response"]
        if revision.status in (
            RevisionRequest.Status.RESOLVED, RevisionRequest.Status.REJECTED,
        ):
            revision.resolved_at = timezone.now()
            revision.resolved_by_id = actor_id
        else:
            revision.resolved_at = None
            revision.resolved_by = None
        revision.save(update_fields=[
            "status", "staff_response", "resolved_at", "resolved_by",
            "updated_at",
        ])
        VideoActivity.objects.create(
            video=revision.version.video,
            kind=VideoActivity.Kind.REVIEW,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"Correction mise à jour : {revision.get_status_display()}.",
            created_by_id=actor_id,
        )
        return revision


PRODUCTION = {
    "video.production.amend": VideoProductionSettings(),
    "video.activity.add": VideoActivityAdd(),
    "video.version.add": VideoVersionAdd(),
    "video.payment_request.add": VideoPaymentRequestAdd(),
    "video.revision.resolve": VideoRevisionResolve(),
}
