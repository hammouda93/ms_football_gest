"""Focused tests for the simple persisted-job agent report."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from .monitoring_report import sync_job_report, video_upload_report


def job_stub(status, result=None, error=""):
    player = SimpleNamespace(name="Alphonce Msanga")
    subscription = SimpleNamespace(player=player)
    return SimpleNamespace(
        pk=796,
        subscription=subscription,
        status=status,
        result_summary=result or {},
        error_message=error,
        created_at=None,
        started_at=None,
        finished_at=None,
        get_job_type_display=lambda: "Profil, saison, matchs et All Actions",
        get_status_display=lambda: status,
    )


def video_stub(status, url="", error=""):
    player = SimpleNamespace(name="Alphonce Msanga")
    subscription = SimpleNamespace(player=player)
    match = SimpleNamespace(
        subscription=subscription, sportsbase_match_id="802053"
    )
    return SimpleNamespace(
        pk=298,
        match=match,
        status=status,
        youtube_url=url,
        dailymotion_url=url,
        error_message=error,
        created_at=None,
        started_at=None,
        finished_at=None,
        get_status_display=lambda: status,
    )


class SimpleAgentReportTests(SimpleTestCase):
    def test_sync_job_has_planned_and_recorded_work(self):
        report = sync_job_report(job_stub(
            "success",
            {"profile_updated": True, "matches_received": 1, "reports_ready": 1}
        ))
        self.assertIn("Profil", report["planned"])
        self.assertIn("1 match(s)", report["observed"])
        self.assertIn("1 rapport(s)", report["observed"])
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["player"], "Alphonce Msanga")

    def test_pending_job_does_not_claim_work(self):
        report = sync_job_report(job_stub("pending"))
        self.assertEqual(report["observed"], "Non commencé")
        self.assertEqual(report["remaining"], "À effectuer")

    def test_failed_job_reports_error_and_remaining_work(self):
        report = sync_job_report(job_stub(
            "failed", error="Téléchargement interrompu"
        ))
        self.assertIn("Erreur à corriger", report["remaining"])
        self.assertIn("Téléchargement interrompu", report["error"])

    def test_youtube_upload_success_needs_link(self):
        report = video_upload_report(
            video_stub("uploaded", url="https://youtu.be/mntTTAmSohM"), "YouTube"
        )
        self.assertEqual(report["status"], "uploaded")
        self.assertIn("enregistré", report["observed"])
        self.assertEqual(report["url"], "https://youtu.be/mntTTAmSohM")

    def test_uploaded_flag_without_url_is_not_claimed_successful(self):
        report = video_upload_report(video_stub("uploaded"), "YouTube")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["status_label"], "À vérifier")
        self.assertEqual(report["url"], "")
        self.assertIn("Aucune publication confirmée", report["observed"])

    def test_link_pending_is_not_confirmed(self):
        report = video_upload_report(video_stub("link_pending"), "Dailymotion")
        self.assertEqual(report["status"], "link_pending")
        self.assertIn("lien final non enregistré", report["observed"])
        self.assertIn("Ajouter le lien", report["remaining"])
