"""Isolated regression tests for Hermes video production contracts."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from client_portal.models import VideoActivity
from gestion_joueurs.models import Player, Video, VideoEditor
from .registry import SIMPLE, catalogue
from .readback import graph, expected_graph
from .effects import effects_context


class VideoParityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="video-owner", email="video-owner@example.invalid",
            password="test-only",
        )
        self.editor_user = User.objects.create_user(
            username="video-editor", password="test-only",
        )
        self.editor = VideoEditor.objects.create(user=self.editor_user)
        self.player = Player.objects.create(
            name="Video Player", club="Example FC",
            league="OC", position="FW",
            email="video-player@example.invalid",
        )
        self.video = Video.objects.create(
            player=self.player, editor=self.editor,
            status=Video.StatusChoices.PENDING,
            advance_payment=Decimal("0.00"),
            total_payment=Decimal("350.00"),
            deadline=timezone.localdate() + timedelta(days=7),
            season="2025/2026",
            club=self.player.club,
            league=self.player.league,
        )

    def fake_plan(self, step, preview, results=None):
        return SimpleNamespace(
            actor_id=self.owner.pk,
            steps=[step],
            snapshots={"__preview__": {"changes": [preview]}},
            results=results or {},
            effects={},
        )

    def test_video_progress_and_visibility_changes_only_reviewed_columns(self):
        adapter = SIMPLE["video.production.amend"]
        values = {
            "id": self.video.pk,
            "matches_processed": 2,
            "seasons_to_process": 2,
            "client_portal_visible": False,
        }
        before = adapter.preview({
            "as": "change", "op": "video.production.amend",
            "values": values,
        }, self.owner.pk)
        self.assertEqual(before["new"]["matches_processed"], 2)
        self.video.refresh_from_db()
        self.assertEqual(self.video.matches_processed, 0)
        obj = adapter.apply(values, self.owner.pk)
        self.assertEqual(obj.pk, self.video.pk)
        self.video.refresh_from_db()
        self.assertEqual(self.video.matches_processed, 2)
        self.assertEqual(self.video.seasons_to_process, 2)
        self.assertFalse(self.video.client_portal_visible)
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)
        self.assertEqual(self.video.total_payment, Decimal("350.00"))

    def test_zero_progress_accepted_and_outside_columns_rejected(self):
        adapter = SIMPLE["video.production.amend"]
        adapter.apply({"id": self.video.pk, "matches_processed": 0}, self.owner.pk)
        self.video.refresh_from_db()
        self.assertEqual(self.video.matches_processed, 0)
        with self.assertRaises(ValueError):
            adapter.cleaned({
                "id": self.video.pk, "status": "delivered",
            }, self.owner.pk)

    def test_activity_uses_existing_form_and_has_no_side_effect(self):
        adapter = SIMPLE["video.activity.add"]
        values = {
            "video": self.video.pk,
            "message": "Montage en cours",
            "visibility": "internal",
        }
        step = {"as": "note", "op": "video.activity.add", "values": values}
        preview = adapter.preview(step, self.owner.pk)
        self.assertFalse(VideoActivity.objects.filter(
            video=self.video, kind="note",
        ).exists())
        with transaction.atomic():
            plan = self.fake_plan(step, preview)
            baseline = graph(plan, {}, _alias="default")
            with effects_context(workflow=True) as effects:
                note = adapter.apply(values, self.owner.pk)
            plan.effects = effects
            plan.results = {"note": note.pk}
            observed = graph(plan, plan.results, _alias="default")
            self.assertEqual(observed, expected_graph(plan, baseline, observed))
        self.assertEqual(note.kind, VideoActivity.Kind.NOTE)
        self.assertEqual(note.visibility, VideoActivity.Visibility.INTERNAL)
        self.assertEqual(note.message, "Montage en cours")

    def test_activity_rejects_non_superuser_and_invalid_visibility(self):
        adapter = SIMPLE["video.activity.add"]
        with self.assertRaises(PermissionError):
            adapter.cleaned({
                "video": self.video.pk, "message": "test",
                "visibility": "internal",
            }, self.editor_user.pk)
        with self.assertRaises(ValueError):
            adapter.cleaned({
                "video": self.video.pk, "message": "test",
                "visibility": "not-real",
            }, self.owner.pk)
        self.assertFalse(VideoActivity.objects.filter(
            video=self.video, kind="note",
        ).exists())

    def test_contracts_are_in_native_allowlist(self):
        from .mount import APPROVED_OPERATIONS
        contracts = catalogue()
        self.assertEqual(set(contracts), APPROVED_OPERATIONS)
        self.assertEqual(
            contracts["video.activity.add"]["required"],
            ["video", "message", "visibility"],
        )

    def check_production_plan_post(self, step):
        adapter = SIMPLE[step["op"]]
        preview = adapter.preview(step, self.owner.pk)
        plan = self.fake_plan(step, preview)
        with transaction.atomic():
            baseline = graph(plan, {}, _alias="default")
            with effects_context(workflow=True) as effects:
                obj = adapter.apply(step["values"], self.owner.pk)
            plan.effects = effects
            plan.results = {step["as"]: obj.pk}
            current = graph(plan, plan.results, _alias="default")
            self.assertEqual(current, expected_graph(plan, baseline, current))
        return obj

    def test_add_video_version_replaces_pending_and_verifies_timeline(self):
        from client_portal.models import VideoVersion
        original = VideoVersion.objects.create(
            video=self.video, version_number=1,
            title="Previous", preview_url="https://example.com/preview/old",
            uploaded_by=self.owner,
        )
        adapter = SIMPLE["video.version.add"]
        step = {
            "as": "version", "op": "video.version.add",
            "values": {
                "video": self.video.pk, "title": "Revision V2",
                "preview_url": "https://example.com/preview/new",
                "final_url": "", "notes": "Check highlights",
            },
        }
        self.assertEqual(adapter.preview(step, self.owner.pk)["new"]["version_number"], 2)
        created = self.check_production_plan_post(step)
        self.assertEqual(created.version_number, 2)
        self.assertEqual(created.status, VideoVersion.Status.PENDING)
        original.refresh_from_db()
        self.assertEqual(original.status, VideoVersion.Status.REPLACED)
        self.assertEqual(VideoActivity.objects.filter(
            video=self.video, kind=VideoActivity.Kind.VERSION,
        ).count(), 1)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)

    def test_add_payment_request_is_not_payment_and_verifies_activity(self):
        from client_portal.models import PaymentRequest
        step = {
            "as": "request", "op": "video.payment_request.add",
            "values": {
                "video": self.video.pk,
                "label": "Acompte client",
                "amount": "125.00",
                "payment_url": "https://payments.example.com/pay/abc",
            },
        }
        created = self.check_production_plan_post(step)
        self.assertEqual(created.status, PaymentRequest.Status.PENDING)
        self.assertEqual(created.amount, Decimal("125.00"))
        self.assertEqual(VideoActivity.objects.filter(
            video=self.video, kind=VideoActivity.Kind.PAYMENT,
        ).count(), 1)
        self.video.refresh_from_db()
        self.assertEqual(self.video.total_payment, Decimal("350.00"))
        self.assertEqual(self.video.advance_payment, Decimal("0.00"))

    def test_payment_link_disallows_embedded_credentials_or_query_tokens(self):
        adapter = SIMPLE["video.payment_request.add"]
        for url in (
            "http://payments.example.com/pay/abc",
            "https://name:pass@payments.example.com/pay/abc",
            "https://payments.example.com/pay/abc?secret=123",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                adapter.cleaned({
                    "video": self.video.pk, "label": "Deposit",
                    "amount": "100.00", "payment_url": url,
                }, self.owner.pk)

    def test_resolve_video_revision_and_verify_client_timeline(self):
        from client_portal.models import VideoVersion, RevisionRequest
        version = VideoVersion.objects.create(
            video=self.video, version_number=1,
            preview_url="https://example.com/preview/one",
            uploaded_by=self.owner,
        )
        revision = RevisionRequest.objects.create(
            version=version, comment="Please extend midfield sequence",
            requested_by=self.editor_user,
        )
        step = {
            "as": "revision", "op": "video.revision.resolve",
            "values": {
                "id": revision.pk,
                "status": RevisionRequest.Status.RESOLVED,
                "staff_response": "Longer sequence added.",
            },
        }
        preview = SIMPLE["video.revision.resolve"].preview(step, self.owner.pk)
        self.assertEqual(preview["old"]["status"], RevisionRequest.Status.OPEN)
        self.assertEqual(preview["new"]["resolved_at"], "set_at_execution")
        resolved = self.check_production_plan_post(step)
        self.assertEqual(resolved.status, RevisionRequest.Status.RESOLVED)
        self.assertEqual(resolved.resolved_by_id, self.owner.pk)
        self.assertIsNotNone(resolved.resolved_at)
        self.assertEqual(VideoActivity.objects.filter(
            video=self.video, kind=VideoActivity.Kind.REVIEW,
        ).count(), 1)

    def test_revision_refuses_out_of_policy_status(self):
        from client_portal.models import VideoVersion, RevisionRequest
        version = VideoVersion.objects.create(
            video=self.video, version_number=1,
            preview_url="https://example.com/preview/one",
        )
        revision = RevisionRequest.objects.create(
            version=version, comment="Wrong scene",
        )
        with self.assertRaises(ValueError):
            SIMPLE["video.revision.resolve"].cleaned({
                "id": revision.pk, "status": "approved",
            }, self.owner.pk)
        revision.refresh_from_db()
        self.assertEqual(revision.status, RevisionRequest.Status.OPEN)

    def test_correct_historical_delivery_date_without_changing_status(self):
        adapter = SIMPLE["video.production.amend"]
        delivery_date = (timezone.localdate() - timedelta(days=2)).isoformat()
        values = {"id": self.video.pk, "delivery_date": delivery_date}
        preview = adapter.preview({
            "as": "datefix", "op": "video.production.amend", "values": values,
        }, self.owner.pk)
        self.assertIsNone(preview["old"]["delivery_date"])
        self.assertEqual(preview["new"]["delivery_date"], delivery_date)
        adapter.apply(values, self.owner.pk)
        self.video.refresh_from_db()
        self.assertEqual(self.video.delivery_date.isoformat(), delivery_date)
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)
        adapter.apply({"id": self.video.pk, "delivery_date": ""}, self.owner.pk)
        self.video.refresh_from_db()
        self.assertIsNone(self.video.delivery_date)

    def test_current_season_is_valid_in_highlights_form_and_contract(self):
        from gestion_joueurs.forms import VideoForm
        from .highlights import HIGHLIGHTS
        self.assertIn(
            "2026/2027",
            HIGHLIGHTS["video.conditions.create"].contract()["schema"]["season"]["enum"],
        )
        data = {
            "editor": self.editor.pk,
            "status": Video.StatusChoices.PENDING,
            "advance_payment": "0",
            "total_payment": "350",
            "deadline": (timezone.localdate() + timedelta(days=10)).isoformat(),
            "season": "2026/2027",
            "seasons_to_process": "1",
            "matches_processed": "0",
        }
        form = VideoForm(data, user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
