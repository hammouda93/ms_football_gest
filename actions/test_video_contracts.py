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
            note = adapter.apply(values, self.owner.pk)
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
