import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .deadline_planning import ACTIVE_PLANNING_STATUSES
from .forms import VideoForm
from .models import AutomationEvent, AutomationRun, AutomationWorker, Invoice, Notification, Payment, Player, Video, VideoEditor
from .presentation_styles import (
    DEFAULT_PRESENTATION_STYLE,
    PRESENTATION_STYLES,
    get_presentation_style,
)
from .premiere_automation import PremiereAutomation
from .sportsbase_playwright import SportsBaseAutomation
from .transfermarkt_assets import build_kling_prompt_text, build_prompt_text
from .transfermarkt_fetcher import refresh_presentation_style_assets
from .utils import set_current_user
from .video_status_whatsapp import (
    NOTIFICATION_PAYMENT_MODES,
    build_notification_whatsapp_url,
    build_status_notification_context,
    get_payment_snapshot,
)

from client_portal.models import (
    Organization,
    OrganizationPlayer,
    PlayerAccess,
    PortalAccessLink,
    PortalProfile,
)
from sportsbase_data.models import (
    PerformanceSubscriptionPayment,
    SportsBaseSubscription,
)


class PresentationStylePromptTests(SimpleTestCase):
    def test_ten_styles_are_available_with_golden_hour_as_default(self):
        self.assertEqual(len(PRESENTATION_STYLES), 10)
        self.assertEqual(
            get_presentation_style("unknown")["value"],
            DEFAULT_PRESENTATION_STYLE,
        )

    def test_selected_indoor_style_drives_image_and_kling_prompts(self):
        data = {"player_name": "Test Player", "club_name": "Test Club"}

        image_prompt = build_prompt_text(data, "premium_locker_room")
        kling_prompt = build_kling_prompt_text(data, "premium_locker_room")

        self.assertIn("Vestiaire premium (Indoor)", image_prompt)
        self.assertIn("refined modern first-team locker room", image_prompt)
        self.assertIn("Vestiaire premium (Indoor)", kling_prompt)
        self.assertIn("Never add outdoor weather", kling_prompt)

    def test_cached_transfermarkt_data_can_switch_style_without_rescraping(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "transfermarkt_data.json").write_text(
                json.dumps({"player_name": "Test Player", "club_name": "Test Club"}),
                encoding="utf-8",
            )

            first = refresh_presentation_style_assets(directory, "stadium_night")
            unchanged = refresh_presentation_style_assets(directory, "stadium_night")
            changed = refresh_presentation_style_assets(directory, "official_club_studio")

            self.assertTrue(first["style_changed"])
            self.assertFalse(unchanged["style_changed"])
            self.assertTrue(changed["style_changed"])
            prompt = Path(changed["chatgpt_image_prompt_path"]).read_text(encoding="utf-8")
            self.assertIn("Studio officiel du club (Studio)", prompt)


class HighlightsYouTubeConfigurationTests(SimpleTestCase):
    def test_delivery_agent_uses_dedicated_highlights_configuration(self):
        source = (Path(__file__).parent / "automation_agent.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('config_prefix="HIGHLIGHTS_YOUTUBE"', source)
        self.assertIn(
            "build_highlights_youtube_uploader(storage_root).upload(job)",
            source,
        )
        self.assertIn("--check-youtube", source)
        self.assertIn("--setup-youtube", source)


class PremiereExportConfigurationTests(SimpleTestCase):
    def test_bundled_youtube_1080p_preset_is_used_when_env_is_empty(self):
        with TemporaryDirectory() as directory:
            premiere_dir = Path(directory) / "Adobe Premiere Pro 2022"
            executable = premiere_dir / "Adobe Premiere Pro.exe"
            preset = (
                premiere_dir
                / "MediaIO"
                / "systempresets"
                / "4E49434B_48323634"
                / "YouTube 1080p HD.epr"
            )
            preset.parent.mkdir(parents=True)
            executable.touch()
            preset.touch()
            automation = PremiereAutomation(premiere_exe=str(executable))

            with patch.dict("os.environ", {"PREMIERE_EXPORT_PRESET": ""}):
                resolved = automation._resolve_export_preset_path()

            self.assertEqual(resolved, str(preset))

    def test_project_context_persists_export_path_and_preset(self):
        with TemporaryDirectory() as directory:
            automation = PremiereAutomation()
            context_path = automation._write_project_context_file(
                Path(directory),
                {
                    "player_name": "Test Player",
                    "final_export_path": "D:/exports/test.mp4",
                    "export_preset_path": "C:/Adobe/YouTube 1080p HD.epr",
                },
            )
            context = json.loads(Path(context_path).read_text(encoding="utf-8"))

            self.assertEqual(context["final_export_path"], "D:/exports/test.mp4")
            self.assertEqual(
                context["export_preset_path"],
                "C:/Adobe/YouTube 1080p HD.epr",
            )


    def test_bridge_exports_directly_without_media_encoder_queue(self):
        bridge_root = Path(__file__).resolve().parent / "premiere_bridge"
        host_source = (
            bridge_root / "host" / "index.jsx"
        ).read_text(encoding="utf-8")
        export_source = host_source.split(
            "$._MSBridge.exportCompletedMain = function () {",
            1,
        )[1]
        panel_source = (
            bridge_root / "client" / "index.js"
        ).read_text(encoding="utf-8")

        self.assertIn("sequence.exportAsMediaDirect(", export_source)
        self.assertIn('return "EXPORT_COMPLETED | output="', export_source)
        self.assertNotIn("app.encoder.encodeSequence(", export_source)
        self.assertNotIn("app.encoder.launchEncoder(", export_source)
        self.assertIn("Export direct de COMPLETED_MAIN", panel_source)
        self.assertNotIn("Adobe Media Encoder", panel_source)


class SportsBasePlayerDownloadTests(SimpleTestCase):
    def test_profile_download_uses_one_chrome_click_and_disk_confirmation(self):
        automation = object.__new__(SportsBaseAutomation)
        automation._cdp_browser = Mock()
        page = Mock()
        download_icon = Mock()
        original = b"\x00\x00\x00\x18ftypmp42sportsbase-original-video"

        with TemporaryDirectory() as directory:
            downloads_dir = Path(directory)
            source = downloads_dir / "Player actions.mp4"
            source.write_bytes(original)
            watch_dirs = [downloads_dir]
            before = {"existing": (1, 1)}
            automation._download_watch_directories = Mock(return_value=watch_dirs)
            automation._configure_native_downloads = Mock(return_value=True)
            automation._snapshot_download_files = Mock(return_value=before)
            automation._wait_for_new_download = Mock(return_value=source)

            detected = automation._download_actions_with_chrome(
                page=page,
                download_icon=download_icon,
                downloads_dir=downloads_dir,
            )

            self.assertEqual(detected.read_bytes(), original)

        download_icon.click.assert_called_once_with(
            timeout=5_000,
            no_wait_after=True,
        )
        automation._wait_for_new_download.assert_called_once_with(
            watch_dirs,
            before,
            timeout_seconds=300,
        )
        page.expect_download.assert_not_called()

    def test_profile_cdp_sets_the_native_chrome_download_directory(self):
        automation = object.__new__(SportsBaseAutomation)
        browser = Mock()
        session = Mock()
        browser.new_browser_cdp_session.return_value = session
        automation._cdp_browser = browser
        page = Mock()

        with TemporaryDirectory() as directory:
            configured = automation._configure_native_downloads(page, directory)

            self.assertTrue(configured)
            session.send.assert_called_once_with(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(Path(directory).resolve()),
                    "eventsEnabled": True,
                },
            )
        page.context.new_cdp_session.assert_not_called()


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class AutomationProgressTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="automation-progress-admin",
            email="automation@example.com",
            password="test-password",
        )
        editor_user = User.objects.create_user(
            username="automation-progress-editor",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=editor_user)
        self.player = Player.objects.create(
            name="Joueur Automation",
            club="Club Automation",
            sportsbase_url="https://example.com/sportsbase/player",
            transfermarkt_url="https://example.com/transfermarkt/player",
        )
        self.video = Video.objects.create(
            player=self.player,
            editor=self.editor,
            status=Video.StatusChoices.IN_PROGRESS,
            advance_payment=Decimal("0.00"),
            total_payment=Decimal("100.00"),
            deadline=timezone.localdate() + timedelta(days=4),
            season="2025/2026",
            club=self.player.club,
            processing_mode=Video.AutomationModeChoices.AUTOMATION,
            intro_automation_enabled=True,
        )
        Invoice.objects.create(
            video=self.video,
            total_amount=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            status="unpaid",
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

    def _json_post(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_atomic_claim_prevents_two_workers_from_receiving_same_video(self):
        url = reverse("claim_automation_job")
        first = self._json_post(url, {
            "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
            "worker_id": "desktop-a",
        })
        same_worker = self._json_post(url, {
            "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
            "worker_id": "desktop-a",
        })
        second = self._json_post(url, {
            "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
            "worker_id": "desktop-b",
        })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["job"]["video_id"], self.video.pk)
        self.assertEqual(
            first.json()["job"]["intro_presentation_style"],
            DEFAULT_PRESENTATION_STYLE,
        )
        self.assertTrue(first.json()["job"]["claim_token"])
        self.assertIsNone(same_worker.json()["job"])
        self.assertIsNone(second.json()["job"])

    def test_repeated_polling_states_are_deduplicated_and_capped(self):
        report_url = reverse("report_automation_progress", args=(self.video.pk,))
        states = (
            {
                "pipeline": AutomationRun.PipelineChoices.INTRO,
                "stage": AutomationRun.StageChoices.TRANSFERMARKT,
                "state": AutomationRun.StateChoices.RUNNING,
                "message": "Vérification des données et visuels Transfermarkt",
            },
            {
                "pipeline": AutomationRun.PipelineChoices.INTRO,
                "stage": AutomationRun.StageChoices.CHATGPT_IMAGE,
                "state": AutomationRun.StateChoices.WAITING_EXTERNAL,
                "message": "Photo du joueur attendue avant la génération ChatGPT",
            },
        )
        for _attempt in range(4):
            for payload in states:
                self.assertEqual(self._json_post(report_url, payload).status_code, 200)

        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.INTRO,
        )
        self.assertEqual(run.events.count(), 2)

        for index in range(20):
            AutomationEvent.objects.create(
                run=run,
                stage=AutomationRun.StageChoices.CHATGPT_IMAGE,
                state=AutomationRun.StateChoices.RUNNING,
                progress_percent=index,
                message=f"Événement {index}",
            )
        self._json_post(report_url, states[-1])
        self.assertEqual(run.events.count(), 12)

    def test_progress_from_an_obsolete_worker_claim_is_rejected(self):
        claim = self._json_post(reverse("claim_automation_job"), {
            "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
            "worker_id": "desktop-a",
        }).json()["job"]

        response = self._json_post(
            reverse("report_automation_progress", args=(self.video.pk,)),
            {
                "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
                "stage": AutomationRun.StageChoices.SPORTSBASE_DOWNLOAD,
                "state": AutomationRun.StateChoices.RUNNING,
                "claim_token": claim["claim_token"] + "-obsolete",
                "message": "Cette mise à jour ne doit pas être acceptée",
            },
        )

        self.assertEqual(response.status_code, 400)
        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.HIGHLIGHTS,
        )
        self.assertNotEqual(run.message, "Cette mise à jour ne doit pas être acceptée")

    def test_waiting_external_recheck_does_not_create_fake_attempts(self):
        report_url = reverse("report_automation_progress", args=(self.video.pk,))
        self._json_post(report_url, {
            "pipeline": AutomationRun.PipelineChoices.INTRO,
            "stage": AutomationRun.StageChoices.CHATGPT_IMAGE,
            "state": AutomationRun.StateChoices.WAITING_EXTERNAL,
            "message": "Image ChatGPT attendue",
        })
        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.INTRO,
        )
        AutomationRun.objects.filter(pk=run.pk).update(
            last_heartbeat_at=timezone.now() - timedelta(minutes=1),
        )

        claim = self._json_post(reverse("claim_automation_job"), {
            "pipeline": AutomationRun.PipelineChoices.INTRO,
            "worker_id": "desktop-a",
        })

        self.assertEqual(claim.status_code, 200)
        self.assertEqual(claim.json()["job"]["video_id"], self.video.pk)
        run.refresh_from_db()
        self.assertEqual(run.attempt_count, 0)
        self.assertEqual(run.events.count(), 1)

    def test_app_status_change_queues_intro_and_highlights(self):
        Video.objects.filter(pk=self.video.pk).update(
            status=Video.StatusChoices.PENDING,
            processing_mode=Video.AutomationModeChoices.NORMAL,
            intro_automation_enabled=False,
        )
        response = self.client.post(
            reverse("update_video_status", args=(self.video.pk,)),
            {
                "status": Video.StatusChoices.IN_PROGRESS,
                "processing_mode": Video.AutomationModeChoices.AUTOMATION,
                "delivery_mode": Video.AutomationModeChoices.AUTOMATION,
                "sportsbase_url": self.player.sportsbase_url,
                "transfermarkt_url": self.player.transfermarkt_url,
                "intro_automation_enabled": "on",
                "intro_presentation_style": "stadium_night",
                "notification_action": "skip",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertEqual(self.video.intro_presentation_style, "stadium_night")
        runs = {
            run.pipeline: run
            for run in AutomationRun.objects.filter(video=self.video)
        }
        self.assertEqual(
            runs[AutomationRun.PipelineChoices.INTRO].state,
            AutomationRun.StateChoices.QUEUED,
        )
        self.assertEqual(
            runs[AutomationRun.PipelineChoices.HIGHLIGHTS].state,
            AutomationRun.StateChoices.QUEUED,
        )

    def test_status_page_displays_all_ten_presentation_styles(self):
        response = self.client.get(
            reverse("update_video_status", args=(self.video.pk,))
        )

        self.assertEqual(response.status_code, 200)
        for style in PRESENTATION_STYLES:
            self.assertContains(response, f'value="{style["value"]}"')

    def test_existing_automation_settings_queue_when_progress_is_missing(self):
        response = self.client.post(
            reverse("update_video_status", args=(self.video.pk,)),
            {
                "status": Video.StatusChoices.IN_PROGRESS,
                "processing_mode": Video.AutomationModeChoices.AUTOMATION,
                "delivery_mode": Video.AutomationModeChoices.AUTOMATION,
                "sportsbase_url": self.player.sportsbase_url,
                "transfermarkt_url": self.player.transfermarkt_url,
                "intro_automation_enabled": "on",
                "notification_action": "skip",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AutomationRun.objects.filter(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.HIGHLIGHTS,
            state=AutomationRun.StateChoices.QUEUED,
        ).exists())
        self.assertTrue(AutomationRun.objects.filter(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.INTRO,
            state=AutomationRun.StateChoices.QUEUED,
        ).exists())

    def test_progress_report_is_durable_and_visible(self):
        report_url = reverse("report_automation_progress", args=(self.video.pk,))
        response = self._json_post(report_url, {
            "pipeline": AutomationRun.PipelineChoices.HIGHLIGHTS,
            "stage": AutomationRun.StageChoices.SPORTSBASE_DOWNLOAD,
            "state": AutomationRun.StateChoices.RUNNING,
            "progress_current": 4,
            "progress_total": 10,
            "progress_percent": 59,
            "message": "4 matchs téléchargés sur 10",
            "artifacts": {"local_folder": "123_Joueur_Automation"},
        })

        self.assertEqual(response.status_code, 200)
        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.HIGHLIGHTS,
        )
        self.assertEqual(run.progress_current, 4)
        self.assertEqual(run.progress_total, 10)
        self.assertEqual(run.progress_percent, 59)
        self.assertEqual(run.events.count(), 1)

        page = self.client.get(reverse("update_video_status", args=(self.video.pk,)))
        self.assertContains(page, "4 matchs téléchargés sur 10")
        self.assertContains(page, "59%")
        self.assertContains(page, "Aucun terminal ni VS Code n’est nécessaire")

    def test_failed_run_can_be_requeued_from_management_app(self):
        report_url = reverse("report_automation_progress", args=(self.video.pk,))
        self._json_post(report_url, {
            "pipeline": AutomationRun.PipelineChoices.INTRO,
            "stage": AutomationRun.StageChoices.KLING_VIDEO,
            "state": AutomationRun.StateChoices.FAILED,
            "message": "Kling indisponible",
            "error_code": "KLING_UNAVAILABLE",
            "error_detail": "La génération n’a pas répondu.",
        })
        retry_url = reverse(
            "retry_automation_progress",
            args=(self.video.pk, AutomationRun.PipelineChoices.INTRO),
        )
        response = self.client.post(retry_url)

        self.assertRedirects(
            response,
            reverse("update_video_status", args=(self.video.pk,)),
        )
        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.INTRO,
        )
        self.assertEqual(run.state, AutomationRun.StateChoices.QUEUED)
        self.assertEqual(run.error_detail, "")

    def test_worker_heartbeat_is_visible_without_a_terminal(self):
        response = self._json_post(reverse("automation_worker_heartbeat"), {
            "worker_id": "office-pc-highlights",
            "display_name": "Agent vidéo Bureau",
            "state": AutomationWorker.StateChoices.IDLE,
            "capabilities": {"premiere": True},
        })

        self.assertEqual(response.status_code, 200)
        status_response = self.client.get(reverse("automation_worker_status"))
        worker = status_response.json()["workers"][0]
        self.assertTrue(worker["is_online"])
        self.assertEqual(worker["state_label"], "Connecté")

    def test_highlights_cannot_complete_without_validated_export(self):
        response = self._json_post(
            reverse("mark_automation_completed", args=(self.video.pk,)),
            {},
        )

        self.assertEqual(response.status_code, 400)
        self.video.refresh_from_db()
        self.assertFalse(self.video.automation_completed)
        self.assertEqual(self.video.status, Video.StatusChoices.IN_PROGRESS)

    def test_youtube_delivery_sets_link_before_waiting_for_whatsapp(self):
        self.video.delivery_mode = Video.AutomationModeChoices.AUTOMATION
        self.video.status = Video.StatusChoices.COMPLETED
        self.video.save(update_fields=("delivery_mode", "status"))
        response = self._json_post(
            reverse("complete_automation_delivery", args=(self.video.pk,)),
            {
                "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
                "validation": {"content_sha256": "a" * 64},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.DELIVERED)
        self.assertEqual(self.video.video_link, "https://youtu.be/dQw4w9WgXcQ")
        run = AutomationRun.objects.get(
            video=self.video,
            pipeline=AutomationRun.PipelineChoices.DELIVERY,
        )
        self.assertEqual(run.current_stage, AutomationRun.StageChoices.WHATSAPP)
        self.assertEqual(run.state, AutomationRun.StateChoices.WAITING_EXTERNAL)


class VideoStatusWhatsappTests(TestCase):
    def setUp(self):
        set_current_user(None)
        self.admin = User.objects.create_superuser(
            username="admin-status-test",
            email="admin@example.com",
            password="test-password",
        )
        editor_user = User.objects.create_user(
            username="editor-status-test",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=editor_user)
        self.player = Player.objects.create(
            name="Joueur Test",
            club="Club Test",
            whatsapp_number="+21620123456",
        )
        self.video = Video.objects.create(
            player=self.player,
            editor=self.editor,
            status=Video.StatusChoices.PENDING,
            advance_payment=Decimal("20.00"),
            total_payment=Decimal("100.00"),
            deadline=timezone.localdate() + timedelta(days=10),
            season="2025/2026",
        )
        self.invoice = Invoice.objects.create(
            video=self.video,
            total_amount=Decimal("100.00"),
            amount_paid=Decimal("20.00"),
            status="partially_paid",
            created_by=self.admin,
        )
        self.client.force_login(self.admin)
        self.url = reverse("update_video_status", args=(self.video.pk,))

    def _post_status(self, status, **overrides):
        data = {
            "status": status,
            "processing_mode": "normal",
            "delivery_mode": "normal",
            "video_link": "",
            "notification_action": "skip",
            "payment_message_mode": "auto",
            "whatsapp_message": "",
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def _edit_video_data(self, status, **overrides):
        data = {
            "status": status,
            "advance_payment": "20.00",
            "total_payment": "100.00",
            "deadline": self.video.deadline.isoformat(),
            "video_link": "",
            "info": "",
            "season": "2025/2026",
            "editor": str(self.editor.pk),
            "seasons_to_process": str(Video.SeasonsToProcessChoices.ONE),
            "notification_action": "skip",
            "payment_message_mode": "auto",
        }
        data.update(overrides)
        return data

    def test_confirmation_dialog_contains_payment_snapshot(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informer Joueur Test du nouveau statut ?")
        self.assertContains(response, "Avance / paiement partiel enregistré")
        self.assertContains(response, "Mettre à jour sans WhatsApp")
        self.assertContains(response, "Mettre à jour et ouvrir WhatsApp")
        self.assertContains(response, "ne sera pas")
        self.assertContains(response, 'form="status-update-form"', count=2)
        self.assertContains(
            response,
            "document.body.appendChild(notificationModal)",
        )

    def test_status_can_be_updated_without_opening_whatsapp(self):
        response = self._post_status(Video.StatusChoices.IN_PROGRESS)

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.IN_PROGRESS)
        self.assertEqual(
            response["Location"],
            reverse("video_status", args=(self.video.pk,)),
        )

    def test_edit_video_status_select_also_contains_notification_question(self):
        response = self.client.get(reverse("edit_video", args=(self.video.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="video-edit-form"')
        self.assertContains(response, 'data-original-status="pending"')
        self.assertContains(response, "Informer Joueur Test du nouveau statut ?")
        self.assertContains(response, "Mettre à jour sans WhatsApp")
        self.assertContains(response, "Mettre à jour et ouvrir WhatsApp")
        self.assertContains(response, 'form="video-edit-form"')
        self.assertContains(
            response,
            "document.body.appendChild(notificationModal)",
        )

    def test_edit_video_status_change_can_open_whatsapp(self):
        response = self.client.post(
            reverse("edit_video", args=(self.video.pk,)),
            self._edit_video_data(
                Video.StatusChoices.IN_PROGRESS,
                notification_action="whatsapp",
                payment_message_mode="advance",
            ),
        )

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.IN_PROGRESS)
        self.assertTrue(response["Location"].startswith("https://wa.me/21620123456"))
        decoded_url = unquote(response["Location"])
        self.assertIn("Nous avons commencé le travail sur ta vidéo", decoded_url)
        self.assertIn("Ton avance a bien été enregistrée", decoded_url)

    def test_in_progress_message_mentions_deadline_and_received_advance(self):
        response = self._post_status(
            Video.StatusChoices.IN_PROGRESS,
            notification_action="whatsapp",
        )

        self.assertTrue(response["Location"].startswith("https://wa.me/21620123456"))
        decoded_url = unquote(response["Location"])
        self.assertIn("Nous avons commencé le travail sur ta vidéo", decoded_url)
        self.assertIn(timezone.localdate().strftime("%d/%m/%Y"), decoded_url)
        self.assertIn(self.video.deadline.strftime("%d/%m/%Y"), decoded_url)
        self.assertIn("Ton avance a bien été enregistrée", decoded_url)
        self.assertIn("solde reste à régler", decoded_url)

    def test_completed_unpaid_message_requests_total_payment(self):
        self.invoice.amount_paid = Decimal("0.00")
        self.invoice.status = "unpaid"
        self.invoice.save(update_fields=("amount_paid", "status"))

        response = self._post_status(
            Video.StatusChoices.COMPLETED,
            notification_action="whatsapp",
        )

        decoded_url = unquote(response["Location"])
        self.assertIn("Ta vidéo est maintenant terminée", decoded_url)
        self.assertIn("le paiement n’est pas encore enregistré", decoded_url)
        self.assertIn("régler le montant total avant la livraison", decoded_url)

    def test_completed_partially_paid_message_requests_balance(self):
        response = self._post_status(
            Video.StatusChoices.COMPLETED,
            notification_action="whatsapp",
        )

        decoded_url = unquote(response["Location"])
        self.assertIn("Ton avance a bien été enregistrée", decoded_url)
        self.assertIn("Le solde reste à régler avant la livraison", decoded_url)

    def test_custom_message_is_preserved(self):
        custom_message = "Bonjour, voici mon message personnalisé."
        response = self._post_status(
            Video.StatusChoices.IN_PROGRESS,
            notification_action="whatsapp",
            whatsapp_message=custom_message,
        )

        decoded_url = unquote(response["Location"])
        self.assertTrue(decoded_url.endswith(f"?text={custom_message}"))

    def test_delivered_custom_message_always_includes_video_link(self):
        video_link = "https://youtu.be/ms-football-test"
        custom_message = "Bonjour, ta vidéo est livrée."

        response = self._post_status(
            Video.StatusChoices.DELIVERED,
            notification_action="whatsapp",
            whatsapp_message=custom_message,
            video_link=video_link,
        )

        decoded_url = unquote(response["Location"])
        self.assertIn(custom_message, decoded_url)
        self.assertIn(f"Voici le lien de la vidéo : {video_link}", decoded_url)

    def test_missing_whatsapp_number_never_opens_external_url(self):
        self.player.whatsapp_number = ""
        self.player.save(update_fields=("whatsapp_number",))

        response = self._post_status(
            Video.StatusChoices.IN_PROGRESS,
            notification_action="whatsapp",
        )

        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.IN_PROGRESS)
        self.assertEqual(
            response["Location"],
            reverse("video_status", args=(self.video.pk,)),
        )

    def test_unchanged_status_does_not_open_whatsapp(self):
        response = self._post_status(
            Video.StatusChoices.PENDING,
            notification_action="whatsapp",
        )

        self.assertEqual(
            response["Location"],
            reverse("video_status", args=(self.video.pk,)),
        )

    def test_invoice_is_used_as_payment_source_of_truth(self):
        self.video.advance_payment = Decimal("100.00")
        self.video.save(update_fields=("advance_payment",))
        self.invoice.amount_paid = Decimal("0.00")
        self.invoice.status = "unpaid"
        self.invoice.save(update_fields=("amount_paid", "status"))

        snapshot = get_payment_snapshot(self.video)

        self.assertEqual(snapshot["status"], "unpaid")
        self.assertEqual(snapshot["amount_paid"], Decimal("0.00"))
        self.assertEqual(snapshot["remaining"], Decimal("100.00"))

    def test_every_video_status_has_a_notification_choice_and_message(self):
        notification_context = build_status_notification_context(self.video)

        expected_statuses = {value for value, _label in Video.StatusChoices.choices}
        self.assertEqual(
            set(notification_context["status_whatsapp_messages"]),
            expected_statuses,
        )
        for status in expected_statuses:
            self.assertTrue(
                notification_context["status_whatsapp_messages"][status]["auto"]
            )
            self.assertIn(
                status,
                notification_context["status_payment_recommendations"],
            )

    def test_overdue_deadline_is_identified_in_status_message(self):
        self.video.deadline = timezone.localdate() - timedelta(days=2)
        self.video.save(update_fields=("deadline",))

        notification_context = build_status_notification_context(self.video)
        message = notification_context["status_whatsapp_messages"][
            Video.StatusChoices.IN_PROGRESS
        ]["auto"]

        self.assertIn("elle est maintenant dépassée", message)

    def _create_video_notification(self, notification_type="completed_unpaid"):
        Video.objects.filter(pk=self.video.pk).update(
            status=Video.StatusChoices.COMPLETED,
        )
        self.video.refresh_from_db()
        self.invoice.amount_paid = Decimal("0.00")
        self.invoice.status = "unpaid"
        self.invoice.save(update_fields=("amount_paid", "status"))
        return Notification.objects.create(
            user=self.admin,
            message="La vidéo est terminée et le paiement reste à régler.",
            notification_type=notification_type,
            video=self.video,
            player=self.player,
            sent_at=timezone.now(),
        )

    def test_video_payment_notification_has_whatsapp_action(self):
        notification = self._create_video_notification()

        whatsapp_url = build_notification_whatsapp_url(notification)

        self.assertTrue(whatsapp_url.startswith("https://wa.me/21620123456"))
        decoded_url = unquote(whatsapp_url)
        self.assertIn("Ta vidéo est maintenant terminée", decoded_url)
        self.assertIn("paiement n’est pas encore enregistré", decoded_url)

    def test_notification_whatsapp_uses_the_notification_date(self):
        notification = self._create_video_notification()
        notification.sent_at = timezone.now() - timedelta(days=5)
        notification.save(update_fields=("sent_at",))

        decoded_url = unquote(build_notification_whatsapp_url(notification))

        self.assertIn(
            timezone.localtime(notification.sent_at).strftime("%d/%m/%Y"),
            decoded_url,
        )

    def test_notification_detail_displays_send_with_whatsapp(self):
        notification = self._create_video_notification()

        response = self.client.get(
            reverse("view_notification", args=(notification.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Envoyer avec WhatsApp")
        self.assertContains(response, "https://wa.me/21620123456")
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_notification_list_has_mobile_and_whatsapp_actions(self):
        self._create_video_notification()

        response = self.client.get(reverse("notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "notification-mobile-card")
        self.assertContains(response, "Envoyer avec WhatsApp")

    def test_internal_salary_notification_has_no_player_whatsapp_action(self):
        notification = self._create_video_notification("unpaid_salary")

        self.assertIsNone(build_notification_whatsapp_url(notification))

    def test_all_existing_video_payment_notification_cases_support_whatsapp(self):
        for notification_type in NOTIFICATION_PAYMENT_MODES:
            with self.subTest(notification_type=notification_type):
                notification = Notification(
                    user=self.admin,
                    message="Notification interne de test.",
                    notification_type=notification_type,
                    video=self.video,
                    player=self.player,
                )
                self.assertTrue(build_notification_whatsapp_url(notification))

    def test_non_superuser_cannot_open_another_users_notification(self):
        notification = self._create_video_notification()
        other_user = User.objects.create_user(
            username="other-notification-user",
            password="test-password",
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("view_notification", args=(notification.pk,))
        )

        self.assertEqual(response.status_code, 404)

    def test_mobile_navbar_keeps_notifications_profile_and_logout_visible(self):
        response = self.client.get(self.url)
        navbar_html = response.content.decode().split("</nav>", 1)[0]

        self.assertIn("navbar-account-actions", navbar_html)
        self.assertIn("Afficher les notifications", navbar_html)
        self.assertIn("Voir Profil", navbar_html)
        self.assertIn("Déconnexion", navbar_html)
        self.assertNotIn("collapse navbar-collapse", navbar_html)

    def test_mobile_notification_dropdown_is_limited_but_count_is_total(self):
        Notification.objects.all().delete()
        for index in range(10):
            Notification.objects.create(
                user=self.admin,
                message=f"Notification {index}",
                notification_type="update",
            )

        response = self.client.get(self.url)

        self.assertEqual(response.context["unread_notifications_count"], 10)
        self.assertEqual(len(response.context["notifications"]), 8)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PlayerPortalProvisioningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="portal-provision-admin",
            email="admin@example.com",
            password="test-password",
        )
        self.editor_user = User.objects.create_user(
            username="portal-provision-editor",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=self.editor_user)
        self.player = Player.objects.create(
            name="Client Account Player",
            club="Account Club",
            email="client-player@example.com",
            whatsapp_number="+21620123123",
            league="L1",
            position="MF",
        )
        set_current_user(self.admin)
        self.client.force_login(self.admin)

    def player_form_data(self, **overrides):
        data = {
            "name": self.player.name,
            "date_of_birth": "",
            "league": self.player.league,
            "club": self.player.club,
            "email": self.player.email,
            "whatsapp_number": self.player.whatsapp_number,
            "position": self.player.position,
            "sportsbase_url": "",
            "transfermarkt_url": "",
            "client_fidel": "",
            "client_vip": "",
        }
        data.update(overrides)
        return data

    def test_player_edit_checkbox_creates_durable_portal_account(self):
        snapshot = (self.player.name, self.player.club, self.player.email)
        response = self.client.post(
            reverse("edit_player", args=(self.player.pk,)),
            self.player_form_data(create_client_account="on"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lien sécurisé prêt")
        profile = PortalProfile.objects.get(user__email=self.player.email)
        self.assertTrue(profile.user.has_usable_password())
        self.assertTrue(
            PlayerAccess.objects.filter(
                user=profile.user,
                player=self.player,
                is_active=True,
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            PortalAccessLink.objects.filter(
                user=profile.user,
                revoked_at__isnull=True,
            ).exists()
        )
        self.assertIn("/portal/access/", mail.outbox[0].body)
        self.player.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            snapshot,
        )

    def test_video_edit_controls_portal_visibility_and_account_creation(self):
        video = Video.objects.create(
            player=self.player,
            editor=self.editor,
            status=Video.StatusChoices.PENDING,
            advance_payment=Decimal("0.00"),
            total_payment=Decimal("200.00"),
            deadline=timezone.localdate() + timedelta(days=10),
            season="2025/2026",
            club=self.player.club,
            league=self.player.league,
        )
        Invoice.objects.create(
            video=video,
            total_amount=Decimal("200.00"),
            amount_paid=Decimal("0.00"),
            status="unpaid",
            created_by=self.admin,
        )

        response = self.client.post(
            reverse("edit_video", args=(video.pk,)),
            {
                "status": Video.StatusChoices.IN_PROGRESS,
                "advance_payment": "0.00",
                "total_payment": "200.00",
                "deadline": video.deadline.isoformat(),
                "video_link": "",
                "client_portal_visible": "on",
                "create_client_account": "on",
                "info": "",
                "season": "2025/2026",
                "editor": self.editor.pk,
                "seasons_to_process": Video.SeasonsToProcessChoices.ONE,
                "notification_action": "whatsapp",
                "payment_message_mode": "auto",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lien sécurisé prêt")
        self.assertContains(response, "Notifier le nouveau statut")
        self.assertTrue(response.context["status_whatsapp_url"].startswith(
            "https://wa.me/21620123123"
        ))
        video.refresh_from_db()
        self.assertEqual(video.status, Video.StatusChoices.IN_PROGRESS)
        self.assertTrue(video.client_portal_visible)
        self.assertTrue(
            PlayerAccess.objects.filter(
                player=self.player,
                user__portal_profile__account_type=PortalProfile.AccountType.PLAYER,
            ).exists()
        )


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class PlayerRelationshipManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="player-relationship-admin",
            email="relationship-admin@example.com",
            password="test-password",
        )
        editor_user = User.objects.create_user(
            username="player-relationship-editor",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=editor_user)
        self.player = Player.objects.create(
            name="Relationship Player",
            club="Relationship Club",
            email="relationship@example.com",
            whatsapp_number="+21622111222",
            league="L1",
            position="MF",
            sportsbase_url="https://football.sportsbase.world/players/456",
            transfermarkt_url="https://www.transfermarkt.fr/player/profil/spieler/123",
        )
        self.empty_player = Player.objects.create(
            name="No Service Player",
            club="No Service Club",
            league="L2",
            position="DF",
        )
        self.agent = Organization.objects.create(
            name="Relationship Agency",
            kind=Organization.Kind.AGENT,
            created_by=self.admin,
        )
        self.academy = Organization.objects.create(
            name="Relationship Academy",
            kind=Organization.Kind.ACADEMY,
            created_by=self.admin,
        )
        set_current_user(self.admin)
        self.client.force_login(self.admin)

    def player_form_data(self):
        return {
            "selected_player_id": str(self.player.pk),
            "add_player": "1",
            "name": self.player.name,
            "date_of_birth": "",
            "league": self.player.league,
            "club": self.player.club,
            "email": self.player.email,
            "whatsapp_number": self.player.whatsapp_number,
            "position": self.player.position,
            "sportsbase_url": self.player.sportsbase_url,
            "transfermarkt_url": self.player.transfermarkt_url,
            "client_fidel": "",
            "client_vip": "",
        }

    def test_player_search_returns_every_prefill_field(self):
        OrganizationPlayer.objects.create(
            organization=self.agent,
            player=self.player,
            added_by=self.admin,
        )
        response = self.client.get(reverse("search_players"), {"q": "Relationship"})

        self.assertEqual(response.status_code, 200)
        player = response.json()["players"][0]
        self.assertEqual(player["sportsbase_url"], self.player.sportsbase_url)
        self.assertEqual(player["transfermarkt_url"], self.player.transfermarkt_url)
        self.assertEqual(player["position"], self.player.position)
        self.assertIn("client_fidel", player)
        self.assertIn("client_vip", player)
        self.assertEqual(player["organization_id"], self.agent.pk)

    def test_new_player_can_be_associated_with_an_agent(self):
        data = self.player_form_data()
        data.update({
            "selected_player_id": "",
            "name": "New Agent Player",
            "email": "new-agent-player@example.com",
            "organization": str(self.agent.pk),
        })

        response = self.client.post(reverse("create_video_request"), data)

        self.assertEqual(response.status_code, 200)
        player = Player.objects.get(name="New Agent Player")
        link = OrganizationPlayer.objects.get(player=player, organization=self.agent)
        self.assertTrue(link.is_active)
        self.assertEqual(link.added_by, self.admin)

    def test_player_sheet_can_add_an_academy_without_removing_agent(self):
        OrganizationPlayer.objects.create(
            organization=self.agent,
            player=self.player,
            added_by=self.admin,
        )
        data = self.player_form_data()
        data.pop("selected_player_id")
        data.pop("add_player")
        data["organization"] = str(self.academy.pk)

        response = self.client.post(
            reverse("edit_player", args=(self.player.pk,)),
            data,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(OrganizationPlayer.objects.filter(
            organization=self.agent,
            player=self.player,
            is_active=True,
        ).exists())
        self.assertTrue(OrganizationPlayer.objects.filter(
            organization=self.academy,
            player=self.player,
            is_active=True,
        ).exists())

    def test_create_page_prefills_existing_player_urls(self):
        response = self.client.get(
            reverse("create_video_request"),
            {"player_id": self.player.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.player.sportsbase_url)
        self.assertContains(response, self.player.transfermarkt_url)
        self.assertContains(response, f'value="{self.player.pk}"')

    def test_performance_create_link_prefills_selected_player(self):
        response = self.client.get(
            reverse("performance:subscription_create"),
            {"player_id": self.player.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["player"], self.player)

    def test_create_page_can_create_performance_subscription_for_selected_player(self):
        data = self.player_form_data()
        data.update({
            "create_performance_subscription": "on",
            "performance-season": "2025/2026",
            "performance-starts_on": timezone.localdate().isoformat(),
            "performance-ends_on": "",
            "performance-sync_from_date": "",
            "performance-first_match_id": "",
            "performance-all_actions_enabled": "on",
            "performance-email_delivery_enabled": "on",
            "performance-report_language": "fr",
            "performance-total_amount": "450.00",
            "performance-currency": "TND",
            "performance-payment_url": "",
            "performance-sync_interval_hours": "24",
            "performance-is_active": "on",
        })

        response = self.client.post(reverse("create_video_request"), data)

        self.assertEqual(response.status_code, 200)
        subscription = SportsBaseSubscription.objects.get(player=self.player)
        self.assertEqual(subscription.total_amount, Decimal("450.00"))
        self.assertEqual(subscription.created_by, self.admin)
        self.assertContains(response, "L’abonnement Performance est prêt")

    def test_player_dashboard_filters_and_detail_show_relationships(self):
        video = Video.objects.create(
            player=self.player,
            editor=self.editor,
            status=Video.StatusChoices.IN_PROGRESS,
            advance_payment=Decimal("100.00"),
            total_payment=Decimal("300.00"),
            deadline=timezone.localdate() + timedelta(days=7),
            season="2025/2026",
            club=self.player.club,
            league=self.player.league,
        )
        invoice = Invoice.objects.create(
            video=video,
            total_amount=Decimal("300.00"),
            amount_paid=Decimal("100.00"),
            status="partially_paid",
            created_by=self.admin,
        )
        Payment.objects.create(
            player=self.player,
            video=video,
            invoice=invoice,
            amount=Decimal("100.00"),
            payment_type="advance",
            remaining_balance=Decimal("200.00"),
            created_by=self.admin,
        )
        subscription = SportsBaseSubscription.objects.create(
            player=self.player,
            season="2025/2026",
            total_amount=Decimal("500.00"),
            created_by=self.admin,
        )
        PerformanceSubscriptionPayment.objects.create(
            subscription=subscription,
            amount=Decimal("200.00"),
            created_by=self.admin,
        )

        list_response = self.client.get(
            reverse("player_dashboard"),
            {"video_relation": "active", "performance_relation": "active"},
        )
        self.assertContains(list_response, self.player.name)
        self.assertNotContains(list_response, self.empty_player.name)
        self.assertContains(list_response, "1 en cours")

        detail_response = self.client.get(reverse("edit_player", args=(self.player.pk,)))
        self.assertContains(detail_response, "Historique des paiements vidéo")
        self.assertContains(detail_response, "Paiements Performance")
        self.assertEqual(
            list(detail_response.context["video_payments"])[0].amount,
            Decimal("100.00"),
        )
        self.assertEqual(
            list(detail_response.context["performance_payments"])[0].amount,
            Decimal("200.00"),
        )


class DeadlinePlanningAssistantTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.admin = User.objects.create_superuser(
            username="admin-deadline-planning",
            email="planning@example.com",
            password="test-password",
        )
        editor_user = User.objects.create_user(
            username="monteur-principal",
            password="test-password",
        )
        other_editor_user = User.objects.create_user(
            username="monteur-secondaire",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=editor_user)
        self.other_editor = VideoEditor.objects.create(user=other_editor_user)
        self.client.force_login(self.admin)

    def make_video(self, *, status, deadline, editor=None, seasons=1, suffix=""):
        player = Player.objects.create(
            name=f"Joueur planning {suffix or Video.objects.count() + 1}",
            club="Club Planning",
        )
        return Video.objects.create(
            player=player,
            editor=editor or self.editor,
            status=status,
            advance_payment=Decimal("0.00"),
            total_payment=Decimal("200.00"),
            deadline=deadline,
            season="2025/2026",
            club=player.club,
            league=player.league,
            seasons_to_process=seasons,
        )

    def form_data(self, video, deadline):
        return {
            "status": video.status,
            "advance_payment": str(video.advance_payment),
            "total_payment": str(video.total_payment),
            "deadline": deadline.isoformat(),
            "video_link": video.video_link or "",
            "client_portal_visible": "on",
            "info": video.info or "",
            "season": video.season,
            "editor": str(video.editor_id),
            "seasons_to_process": str(video.seasons_to_process),
        }

    def test_only_work_statuses_are_counted(self):
        selected_date = self.today + timedelta(days=6)
        included_pending = self.make_video(
            status=Video.StatusChoices.PENDING,
            deadline=selected_date,
            suffix="pending",
        )
        included_progress = self.make_video(
            status=Video.StatusChoices.IN_PROGRESS,
            deadline=selected_date,
            editor=self.other_editor,
            seasons=2,
            suffix="progress",
        )
        included_collab = self.make_video(
            status=Video.StatusChoices.COMPLETED_COLLAB,
            deadline=selected_date + timedelta(days=1),
            suffix="collab",
        )
        for status in (
            Video.StatusChoices.COMPLETED,
            Video.StatusChoices.DELIVERED,
            Video.StatusChoices.PROBLEMATIC,
        ):
            self.make_video(
                status=status,
                deadline=selected_date,
                suffix=status,
            )

        before = list(Video.objects.values_list("pk", "deadline", "status"))
        response = self.client.get(
            reverse("deadline_planning_assistant"),
            {
                "date": selected_date.isoformat(),
                "editor_id": self.editor.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(ACTIVE_PLANNING_STATUSES), {
            Video.StatusChoices.PENDING,
            Video.StatusChoices.IN_PROGRESS,
            Video.StatusChoices.COMPLETED_COLLAB,
        })
        self.assertEqual(payload["summary"]["active_count"], 3)
        self.assertEqual(payload["summary"]["finishing_count"], 1)
        self.assertEqual(payload["selection"]["global_count"], 2)
        self.assertEqual(payload["selection"]["editor_count"], 1)
        self.assertEqual(
            {video["id"] for video in payload["period_videos"]},
            {included_pending.pk, included_progress.pk, included_collab.pk},
        )
        self.assertEqual(len(payload["calendar"]), 28)
        self.assertEqual(len(payload["suggestions"]), 3)
        self.assertEqual(
            list(Video.objects.values_list("pk", "deadline", "status")),
            before,
        )

    def test_current_video_is_excluded_from_edit_planning(self):
        selected_date = self.today + timedelta(days=4)
        current_video = self.make_video(
            status=Video.StatusChoices.IN_PROGRESS,
            deadline=selected_date,
            suffix="current",
        )
        other_video = self.make_video(
            status=Video.StatusChoices.PENDING,
            deadline=selected_date,
            suffix="other",
        )

        response = self.client.get(
            reverse("deadline_planning_assistant"),
            {
                "date": selected_date.isoformat(),
                "exclude_video_id": current_video.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["selection"]["global_count"], 1)
        self.assertEqual(
            [video["id"] for video in payload["period_videos"]],
            [other_video.pk],
        )

    def test_create_rejects_a_past_deadline_but_edit_allows_it(self):
        past_deadline = self.today - timedelta(days=5)
        video = self.make_video(
            status=Video.StatusChoices.PENDING,
            deadline=self.today + timedelta(days=8),
            suffix="past-edit",
        )
        create_form = VideoForm(
            data=self.form_data(video, past_deadline),
            user=self.admin,
        )
        self.assertFalse(create_form.is_valid())
        self.assertIn("passé", create_form.errors["deadline"][0])
        self.assertEqual(
            create_form.fields["deadline"].widget.attrs["min"],
            self.today.isoformat(),
        )

        edit_form = VideoForm(
            data=self.form_data(video, past_deadline),
            instance=video,
            user=self.admin,
        )
        self.assertTrue(edit_form.is_valid(), edit_form.errors)
        self.assertNotIn("min", edit_form.fields["deadline"].widget.attrs)
        edit_form.save()
        video.refresh_from_db()
        self.assertEqual(video.deadline, past_deadline)

    def test_edit_page_exposes_non_blocking_assistant(self):
        video = self.make_video(
            status=Video.StatusChoices.IN_PROGRESS,
            deadline=self.today - timedelta(days=2),
            suffix="template",
        )

        response = self.client.get(reverse("edit_video", args=(video.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistant de planification")
        self.assertContains(response, 'data-mode="edit"')
        self.assertContains(response, f'data-exclude-video-id="{video.pk}"')
        self.assertContains(response, "deadline_planner.js")
        self.assertContains(response, "Une deadline passée reste modifiable")

    def test_create_page_exposes_non_blocking_assistant(self):
        video = self.make_video(
            status=Video.StatusChoices.PENDING,
            deadline=self.today + timedelta(days=8),
            suffix="create-template",
        )

        response = self.client.get(
            reverse("create_video_request"),
            {"player_id": video.player_id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistant de planification")
        self.assertContains(response, 'data-mode="create"')
        self.assertContains(response, "deadline_planner.js")
        self.assertContains(response, "Choisissez librement une date future")

    def test_invalid_planning_date_is_rejected(self):
        response = self.client.get(
            reverse("deadline_planning_assistant"),
            {"date": "21-08-2026"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("AAAA-MM-JJ", response.json()["error"])
