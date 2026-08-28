import base64
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from django.core import mail
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from client_portal.models import (
    Organization,
    OrganizationMembership,
    OrganizationPlayer,
    PlayerAccess,
    PortalProfile,
)
from gestion_joueurs.models import Player

from .forms import SportsBaseSubscriptionForm
from .analysis_engine import SPORTSBASE_PLAYER_COLUMNS
from .models import (
    PerformanceReport,
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
    SportsBaseYouTubeUpload,
)
from .reports import (
    generate_match_report,
    generate_reports_for_subscription,
    render_report_pdf,
    send_ready_delivery_notification,
)
from .scraper import SportsBaseSubscriptionScraper
from .services import (
    apply_sync_result,
    apply_youtube_upload_result,
    claim_next_job,
    claim_next_youtube_upload,
    ensure_youtube_upload_jobs,
    queue_sync,
)
from .youtube_uploader import YouTubeStudioUploader, YouTubeUploadError


PNG = b"\x89PNG\r\n\x1a\n" + b"test-png-content"


class SportsBaseFixtureMixin:
    def setUp(self):
        self.admin = User.objects.create_superuser(
            "performance-admin", "admin@example.com", "password"
        )
        self.player = Player.objects.create(
            name="Performance Player",
            club="Stade Tunisien",
            email="player@example.com",
            sportsbase_url="https://football.sportsbase.world/players/575815",
        )
        self.other_player = Player.objects.create(
            name="Private Player",
            club="Club Privé",
            email="private@example.com",
            sportsbase_url="https://football.sportsbase.world/players/999999",
        )
        self.subscription = SportsBaseSubscription.objects.create(
            player=self.player,
            season="2025/2026",
            starts_on=timezone.localdate(),
            created_by=self.admin,
        )
        self.other_subscription = SportsBaseSubscription.objects.create(
            player=self.other_player,
            season="2025/2026",
            starts_on=timezone.localdate(),
            created_by=self.admin,
        )

    def portal_user(self, username="client", account_type=PortalProfile.AccountType.PLAYER):
        user = User.objects.create_user(username, password="password")
        PortalProfile.objects.create(
            user=user,
            account_type=account_type,
            display_name=username.title(),
            created_by=self.admin,
        )
        return user


class SubscriptionModelTests(SportsBaseFixtureMixin, TestCase):
    def test_subscription_is_additive_and_does_not_change_player(self):
        original = (self.player.name, self.player.club, self.player.email)
        self.subscription.is_active = False
        self.subscription.save()
        self.player.refresh_from_db()
        self.assertEqual((self.player.name, self.player.club, self.player.email), original)

    def test_form_rejects_active_subscription_without_sportsbase_url(self):
        player = Player.objects.create(name="Sans lien", club="Club", email="none@example.com")
        form = SportsBaseSubscriptionForm(
            data={
                "player": player.pk,
                "season": "2025/2026",
                "starts_on": timezone.localdate(),
                "sync_interval_hours": 24,
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("player", form.errors)

    def test_access_expiry_hides_subscription(self):
        self.subscription.ends_on = timezone.localdate() - timedelta(days=1)
        self.subscription.save()
        self.assertFalse(self.subscription.access_enabled)

    def test_email_subscription_is_complete_only_after_delivery(self):
        match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id="770001",
            season=self.subscription.season,
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            actions_state=SportsBaseMatch.ActionsState.DOWNLOADED,
        )
        self.assertFalse(match.is_complete)
        match.actions_state = SportsBaseMatch.ActionsState.EMAILED
        self.assertTrue(match.is_complete)


class SyncServiceTests(SportsBaseFixtureMixin, TestCase):
    def test_pending_jobs_api_previews_every_player_without_claiming_jobs(self):
        sync_job, _created = queue_sync(self.subscription, requested_by=self.admin)
        match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id="772538",
            season=self.subscription.season,
            home_team="Stade Tunisien",
            away_team="CS Sfaxien",
            home_score=1,
            away_score=1,
        )
        youtube_job = SportsBaseYouTubeUpload.objects.create(match=match)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("performance:api_pending_jobs"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        player_names = {
            item["player"]["name"] for item in payload["sportsbase_jobs"]
        }
        self.assertEqual(player_names, {"Performance Player", "Private Player"})
        self.assertEqual(payload["youtube_jobs"][0]["player"]["name"], "Performance Player")
        sync_job.refresh_from_db()
        youtube_job.refresh_from_db()
        self.assertEqual(sync_job.status, SportsBaseSyncJob.Status.PENDING)
        self.assertEqual(youtube_job.status, SportsBaseYouTubeUpload.Status.PENDING)

    def test_job_payload_contains_only_operational_player_data(self):
        job, created = queue_sync(self.subscription, requested_by=self.admin)
        self.assertTrue(created)
        claimed = claim_next_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.payload["player"]["id"], self.player.pk)
        self.assertEqual(claimed.payload["season"], "2025/2026")
        self.assertNotIn("password", claimed.payload)

    def test_job_payload_exposes_stored_players_statistics_headers(self):
        match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id="772538",
            season=self.subscription.season,
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            actions_state=SportsBaseMatch.ActionsState.DOWNLOADED,
        )
        SportsBaseMatchStats.objects.create(
            match=match,
            players_statistics_headers=["Player", "Team", "Headers"],
        )
        queue_sync(self.subscription, requested_by=self.admin)

        claimed = claim_next_job()

        self.assertEqual(
            claimed.payload["known_matches"][0]["players_statistics_headers"],
            ["Player", "Team", "Headers"],
        )

    def test_result_upserts_profile_match_stats_and_maps(self):
        job, _created = queue_sync(self.subscription, requested_by=self.admin)
        claimed = claim_next_job()
        encoded = base64.b64encode(PNG).decode("ascii")
        result = {
            "status": "success",
            "profile": {
                "season": "2025/2026",
                "sportsbase_player_id": "575815",
                "sportsbase_player_name": "Performance Player",
                "club_name": "Stade Tunisien",
                "season_statistics": {"Matches played": "12"},
                "heatmap_png_base64": encoded,
                "ball_touches_png_base64": encoded,
                "radar_png_base64": encoded,
            },
            "matches": [
                {
                    "sportsbase_match_id": "772538",
                    "match_date": "2026-08-20",
                    "home_team": "Stade Tunisien",
                    "away_team": "Gabès",
                    "home_score": 2,
                    "away_score": 0,
                    "sync_state": "synced",
                    "actions_state": "emailed",
                    "all_actions_filename": "actions.mp4",
                    "stats": {
                        "team_name": "Stade Tunisien",
                        "index": 201,
                        "team_rank": 1,
                        "match_rank": 2,
                        "summary_statistics": {"Shots": "3"},
                        "heatmap_png_base64": encoded,
                    },
                }
            ],
        }
        apply_sync_result(claimed, result)
        self.assertEqual(SportsBaseSeasonSnapshot.objects.count(), 1)
        snapshot = SportsBaseSeasonSnapshot.objects.get()
        self.assertEqual(bytes(snapshot.heatmap_png), PNG)
        match = SportsBaseMatch.objects.get(sportsbase_match_id="772538")
        self.assertEqual(match.score, "2–0")
        self.assertEqual(match.player_stats.index, 201)
        self.assertEqual(bytes(match.player_stats.heatmap_png), PNG)

        second_job, _created = queue_sync(self.subscription, requested_by=self.admin)
        second_job.status = SportsBaseSyncJob.Status.RUNNING
        second_job.save(update_fields=("status",))
        apply_sync_result(second_job, result)
        self.assertEqual(SportsBaseSeasonSnapshot.objects.count(), 1)
        self.assertEqual(SportsBaseMatch.objects.count(), 1)
        self.assertEqual(SportsBaseMatchStats.objects.count(), 1)

    def test_invalid_map_is_rejected_without_partial_database_write(self):
        job, _created = queue_sync(self.subscription)
        claimed = claim_next_job()
        with self.assertRaises(ValueError):
            apply_sync_result(
                claimed,
                {
                    "status": "success",
                    "profile": {
                        "season": "2025/2026",
                        "heatmap_png_base64": base64.b64encode(b"not-png").decode(),
                    },
                },
            )
        self.assertFalse(SportsBaseSeasonSnapshot.objects.exists())

    def test_invalid_api_result_marks_job_failed_instead_of_leaving_it_running(self):
        job, _created = queue_sync(self.subscription)
        claimed = claim_next_job()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("performance:api_job_result", args=(claimed.pk,)),
            data={
                "status": "success",
                "profile": {
                    "season": "2025/2026",
                    "heatmap_png_base64": base64.b64encode(b"not-png").decode(),
                },
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(job.status, SportsBaseSyncJob.Status.FAILED)
        self.assertEqual(
            self.subscription.last_sync_state,
            SportsBaseSubscription.SyncState.FAILED,
        )


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class PortalPerformanceTests(SportsBaseFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.snapshot = SportsBaseSeasonSnapshot.objects.create(
            subscription=self.subscription,
            season=self.subscription.season,
            sportsbase_player_name=self.player.name,
            heatmap_png=PNG,
            time_on_field_percent=45,
            season_statistics={
                "Index": "180",
                "Matches played": "12",
                "Passes": "540",
                "Passes accurate, %": "86%",
                "Challenges": "120",
                "Challenges won, %": "61%",
                "Goals": "4",
                "Assists": "3",
            },
            average_statistics={
                "Passes": "45",
                "Passes accurate, %": "86%",
                "Challenges": "10",
                "Challenges won, %": "61%",
                "Goals": "0.33",
            },
            season_table_headers=["Index", "Passes"],
            season_match_rows=[{"sportsbase_match_id": "772538", "values": ["201", "45"]}],
        )
        self.match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id="772538",
            season=self.subscription.season,
            home_team="Stade Tunisien",
            away_team="Gabès",
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            actions_state=SportsBaseMatch.ActionsState.GENERATING,
            delivery_error="Erreur de génération SportsBase réservée à l’équipe.",
        )
        SportsBaseMatchStats.objects.create(
            match=self.match,
            team_name="Stade Tunisien",
            index=201,
            minutes_played=90,
            summary_statistics={
                "Passes": "45",
                "Challenges": "8",
                "Shots": "3",
                "Goals": "1",
            },
            success_rates={
                "Passes accurate, %": "89%",
                "Challenges won, %": "62%",
                "Shots on target, %": "67%",
            },
            detailed_statistics={
                "Passes": "45",
                "Passes accurate, %": "89%",
                "Goals": "1",
                "Key passes": "2",
            },
            team_table=[
                {
                    "rank": 1,
                    "player_name": self.player.name,
                    "index": 201,
                    "position": "CM",
                    "minutes": 90,
                    "is_current_player": True,
                }
            ],
        )

    def test_player_sees_only_his_active_performance(self):
        user = self.portal_user()
        PlayerAccess.objects.create(user=user, player=self.player)
        self.client.force_login(user)
        response = self.client.get(reverse("performance:portal_overview"))
        self.assertContains(response, self.player.name)
        self.assertNotContains(response, self.other_player.name)
        self.assertContains(response, "Suivi vidéo")
        self.assertContains(response, "Performance")

    def test_agent_sees_multiple_linked_players(self):
        user = self.portal_user("agent", PortalProfile.AccountType.AGENT)
        organization = Organization.objects.create(name="Agent Football")
        OrganizationMembership.objects.create(organization=organization, user=user)
        OrganizationPlayer.objects.create(organization=organization, player=self.player)
        OrganizationPlayer.objects.create(organization=organization, player=self.other_player)
        self.client.force_login(user)
        response = self.client.get(reverse("performance:portal_overview"))
        self.assertContains(response, self.player.name)
        self.assertContains(response, self.other_player.name)

    def test_unrelated_portal_user_cannot_open_player_or_map(self):
        user = self.portal_user("outsider")
        self.client.force_login(user)
        detail = self.client.get(reverse("performance:portal_detail", args=(self.player.pk,)))
        map_response = self.client.get(
            reverse("performance:portal_season_map", args=(self.player.pk, "heatmap"))
        )
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(map_response.status_code, 404)

    def test_authorized_map_is_private_png(self):
        user = self.portal_user("map-user")
        PlayerAccess.objects.create(user=user, player=self.player)
        self.client.force_login(user)
        response = self.client.get(
            reverse("performance:portal_season_map", args=(self.player.pk, "heatmap"))
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, PNG)

    def test_performance_and_match_pages_render_complete_navigation(self):
        user = self.portal_user("details-user")
        PlayerAccess.objects.create(user=user, player=self.player)
        SportsBaseYouTubeUpload.objects.create(
            match=self.match,
            status=SportsBaseYouTubeUpload.Status.UPLOADED,
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            youtube_video_id="abcdefghijk",
        )
        self.client.force_login(user)
        detail = self.client.get(
            reverse("performance:portal_detail", args=(self.player.pk,))
        )
        match = self.client.get(
            reverse(
                "performance:portal_match",
                args=(self.player.pk, self.match.sportsbase_match_id),
            )
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Tableau statistique de la saison")
        self.assertContains(detail, "Suivi vidéo")
        self.assertContains(detail, "Matchs du joueur")
        self.assertContains(detail, "Fiche et repères du joueur")
        self.assertContains(detail, "Volume, efficacité et rythme")
        self.assertContains(detail, "Passes réussies")
        self.assertContains(detail, "540")
        self.assertContains(detail, "86%")
        self.assertContains(detail, "45")
        self.assertContains(detail, "performance-analysis-card")
        self.assertContains(detail, "45%")
        self.assertContains(detail, "--analysis-progress: 86.0%")
        html = detail.content.decode()
        self.assertLess(html.index("Index"), html.index("Matchs joués"))
        self.assertLess(html.index("Matchs joués"), html.index("Buts"))
        self.assertLess(html.index("Buts"), html.index("Passes décisives"))
        season_pairs = detail.context["season_analysis_pairs"]
        season_passes = next(
            item for item in season_pairs if item["name"] == "Passes"
        )
        self.assertEqual(season_passes["value"], "540")
        self.assertEqual(season_passes["average_value"], "45")
        self.assertEqual(season_passes["rate_value"], "86%")
        self.assertEqual(season_passes["chart_percent"], 86.0)
        self.assertNotContains(detail, "SportsBase")
        self.assertEqual(match.status_code, 200)
        self.assertContains(match, "Index du match")
        self.assertContains(match, "Volume et efficacité")
        self.assertContains(match, "Passes réussies")
        self.assertContains(match, "89%")
        self.assertContains(match, "Autres repères du match")
        self.assertContains(match, "Vue collective")
        self.assertContains(match, "All Actions")
        self.assertNotContains(match, "Analyse complète")
        self.assertNotContains(match, "Indicateurs avancés")
        self.assertNotContains(match, "Match 772538")
        self.assertNotContains(match, "SportsBase")

        paired = match.context["analysis_pairs"]
        passes = next(item for item in paired if item["name"] == "Passes")
        self.assertEqual(passes["value"], "45")
        self.assertEqual(passes["rate_value"], "89%")
        self.assertEqual(passes["chart_percent"], 89.0)
        self.assertTrue(passes["has_rate"])
        self.assertContains(match, "--analysis-progress: 89.0%")
        self.assertContains(match, "youtube-nocookie.com/embed/abcdefghijk")
        self.assertNotContains(match, "all-actions-open-link")

    def test_average_only_season_metrics_keep_source_order_and_values(self):
        self.snapshot.season_statistics = {
            "Index": "180",
            "Matches played": "16",
            "Goals": "1",
            "Assists": "2",
        }
        self.snapshot.average_statistics = {
            "Key passes": "0.12",
            "Shots": "0.38",
            "Crosses": "1.25",
            "Challenges": "6.75",
            "Challenges won, %": "59%",
            "Aerial challenges": "1.44",
            "Aerial challenges won, %": "52%",
            "Dribbles": "1.12",
            "Dribbles successful, %": "67%",
            "Tackles": "1.25",
        }
        self.snapshot.save(update_fields=("season_statistics", "average_statistics"))
        user = self.portal_user("season-order-user")
        PlayerAccess.objects.create(user=user, player=self.player)
        self.client.force_login(user)

        response = self.client.get(
            reverse("performance:portal_detail", args=(self.player.pk,))
        )
        self.assertEqual(response.status_code, 200)
        pairs = response.context["season_analysis_pairs"]
        self.assertEqual(
            [item["name"] for item in pairs],
            [
                "Key passes",
                "Shots",
                "Crosses",
                "Challenges",
                "Aerial challenges",
                "Dribbles",
                "Tackles",
            ],
        )
        duels = next(item for item in pairs if item["name"] == "Challenges")
        self.assertEqual(duels["value"], "6.75")
        self.assertTrue(duels["value_is_average"])
        self.assertEqual(duels["rate_value"], "59%")
        self.assertContains(response, "6.75")
        self.assertContains(response, "1.44")
        self.assertContains(response, "1.12")


class ScraperNormalizationTests(TestCase):
    def test_pitch_background_is_opaque_and_contains_pitch_lines(self):
        pitch = SportsBaseSubscriptionScraper._render_pitch_background(
            545, 360
        )

        self.assertEqual(pitch.size, (545, 360))
        self.assertEqual(pitch.mode, "RGBA")
        self.assertEqual(pitch.getchannel("A").getextrema(), (255, 255))
        centre_line = pitch.getpixel((272, 18))
        grass = pitch.getpixel((250, 80))
        self.assertGreater(sum(centre_line[:3]), sum(grass[:3]) + 150)

    def test_ball_touches_keep_coordinates_on_pitch(self):
        png = SportsBaseSubscriptionScraper._render_ball_touches_overlay(
            {
                "width": 545,
                "height": 360,
                "points": [
                    {
                        "left_pct": 50,
                        "top_pct": 50,
                        "width_px": 8,
                        "height_px": 8,
                        "color": "rgb(220, 35, 55)",
                    }
                ],
            }
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (545, 360))
            self.assertEqual(image.mode, "RGB")
            red, green, blue = image.getpixel((272, 180))
            self.assertGreater(red, green * 3)
            self.assertGreater(red, blue * 2)

    def test_heatmap_overlay_is_composited_on_pitch(self):
        overlay = Image.new("RGBA", (405, 268), (0, 0, 0, 0))
        ImageDraw.Draw(overlay, "RGBA").ellipse(
            (172, 104, 232, 164),
            fill=(245, 55, 35, 180),
        )
        source = BytesIO()
        overlay.save(source, format="PNG")

        png = SportsBaseSubscriptionScraper._compose_map_on_pitch(
            source.getvalue()
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (405, 268))
            self.assertEqual(image.mode, "RGB")
            red, green, blue = image.getpixel((202, 134))
            self.assertGreater(red, green)
            self.assertGreater(red, blue)

    def test_season_and_average_sections_remain_separate(self):
        class FakePage:
            def __init__(self):
                self.calls = 0
                self.waited = []

            def evaluate(self, _script):
                self.calls += 1
                if self.calls == 1:
                    return True
                return {
                    "season": {
                        "Index": "169",
                        "Matches played": "25",
                        "Goals": "6",
                    },
                    "averages": {
                        "Key passes": "0.4",
                        "Shots": "1.8",
                        "Challenges won, %": "30%",
                    },
                    "table": {"headers": [], "rows": []},
                }

            def wait_for_timeout(self, milliseconds):
                self.waited.append(milliseconds)

        page = FakePage()
        result = SportsBaseSubscriptionScraper._read_season_statistics(
            object(), page
        )

        self.assertEqual(result["season_statistics"]["Matches played"], "25")
        self.assertEqual(result["season_statistics"]["Goals"], "6")
        self.assertNotIn("Shots", result["season_statistics"])
        self.assertEqual(result["average_statistics"]["Shots"], "1.8")
        self.assertEqual(
            result["average_statistics"]["Challenges won, %"], "30%"
        )
        self.assertEqual(page.waited, [450])

    def test_position_comparison_radar_is_a_valid_portal_png(self):
        metrics = [
            {"label": "Shots", "player": 0.86, "average": 1.19, "player_normalized": 35.8, "average_normalized": 49.6, "scale_max": 2.4, "precision": 2, "unit": "per_90"},
            {"label": "Passes into the penalty box accurate, %", "player": 93, "average": 71, "player_normalized": 93, "average_normalized": 71, "scale_max": 100, "precision": 0, "unit": "%"},
            {
                "label": "Defensive challenges",
                "player": 9.14,
                "average": 7.18,
                "player_normalized": 89.9,
                "average_normalized": 70.6,
                "scale_max": 10.17,
                "precision": 2,
                "unit": "per_90",
            },
            {"label": "Interceptions", "player": 3.37, "average": 3.36, "player_normalized": 55.4, "average_normalized": 55.3, "scale_max": 6.10, "precision": 2, "unit": "per_90"},
        ]

        png = SportsBaseSubscriptionScraper._build_position_comparison_radar(
            metrics,
            player_name="Iyed Belwafi",
            position_label="Left attacking midfielder",
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.size, (1400, 1150))

    def test_team_table_marks_player_and_calculates_ranks(self):
        rows = [
            {"headers": ["Player", "Index", "Pos", "Min"], "cells": []},
            {
                "headers": [],
                "cells": ["First Player", "225", "CF", "90"],
                "playerName": "First Player",
                "playerHref": "/players/111",
            },
            {
                "headers": [],
                "cells": ["Target Player", "201", "LW", "75"],
                "playerName": "Target Player",
                "playerHref": "/players/575815",
            },
        ]
        result = SportsBaseSubscriptionScraper._normalize_team_table(
            rows, "575815", "Stade Tunisien"
        )
        self.assertEqual(result["index"], 201)
        self.assertEqual(result["team_rank"], 2)
        self.assertEqual(result["match_rank"], 2)
        self.assertTrue(result["team_table"][1]["is_current_player"])

    def test_direct_players_table_snapshot_preserves_values_and_teams(self):
        snapshot = SportsBaseSubscriptionScraper._normalize_players_table_snapshot(
            {
                "headers": [
                    "№", "Player", "Team", "Index", "Headers",
                    "Headers on target, %",
                ],
                "rows": [
                    {
                        "№": "9",
                        "Player": "  Test  Striker ",
                        "Team": " Team A ",
                        "Index": "170",
                        "Headers": "3",
                        "Headers on target, %": "67%",
                    }
                ],
            }
        )
        self.assertEqual(snapshot["rows"][0]["Player"], "Test Striker")
        self.assertEqual(snapshot["rows"][0]["Team"], "Team A")
        self.assertEqual(snapshot["rows"][0]["Headers"], 3)
        self.assertEqual(snapshot["rows"][0]["Headers on target, %"], "67%")

    def test_players_table_requires_enriched_custom_headers(self):
        enriched = [
            header
            for header in SPORTSBASE_PLAYER_COLUMNS
            if header not in {"№", "Player", "Team"}
        ]
        self.assertEqual(
            SportsBaseSubscriptionScraper._missing_enriched_players_headers(enriched),
            [],
        )
        missing = SportsBaseSubscriptionScraper._missing_enriched_players_headers(
            ["Player", "Shots", "Shots on target, %"]
        )
        self.assertIn("Headers", missing)
        self.assertIn("Shots on target from the penalty area, %", missing)
        self.assertNotIn("Player", missing)

    def test_xlsx_requires_complete_81_column_analysis_contract(self):
        self.assertEqual(
            SportsBaseSubscriptionScraper._missing_xlsx_analysis_headers(
                SPORTSBASE_PLAYER_COLUMNS
            ),
            [],
        )
        missing = SportsBaseSubscriptionScraper._missing_xlsx_analysis_headers(
            [header for header in SPORTSBASE_PLAYER_COLUMNS if header != "Player"]
        )
        self.assertEqual(missing, ["Player"])

    def test_direct_players_table_keeps_only_analysis_contract_columns(self):
        snapshot = SportsBaseSubscriptionScraper._normalize_players_table_snapshot(
            {
                "headers": [
                    "№", "Player", "Team", "Index", "Headers", "Unused metric",
                ],
                "rows": [
                    {
                        "№": "9",
                        "Player": "Test Striker",
                        "Team": "Team A",
                        "Index": "170",
                        "Headers": "3",
                        "Unused metric": "999",
                    }
                ],
            }
        )
        self.assertNotIn("Unused metric", snapshot["headers"])
        self.assertNotIn("Unused metric", snapshot["rows"][0])


class YouTubeDeliveryServiceTests(SportsBaseFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.subscription.youtube_delivery_enabled = True
        self.subscription.save(update_fields=("youtube_delivery_enabled", "updated_at"))
        self.match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id="880001",
            season=self.subscription.season,
            match_date=timezone.localdate(),
            home_team="Stade Tunisien",
            away_team="CS Sfaxien",
            home_score=1,
            away_score=0,
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            actions_state=SportsBaseMatch.ActionsState.DOWNLOADED,
            local_folder_key="player_1/season/match_880001",
            all_actions_filename="all-actions.mp4",
        )
        SportsBaseMatchStats.objects.create(
            match=self.match,
            minutes_played=90,
            detailed_statistics={
                "Passes": "40",
                "Passes accurate, %": "88%",
            },
        )

    def test_upload_queue_is_idempotent_and_contains_no_source_brand(self):
        self.assertEqual(ensure_youtube_upload_jobs(), 1)
        self.assertEqual(ensure_youtube_upload_jobs(), 0)
        upload = claim_next_youtube_upload()
        self.assertEqual(upload.match, self.match)
        self.assertEqual(upload.payload["youtube"]["visibility"], "unlisted")
        self.assertNotIn("sportsbase", str(upload.payload).casefold())
        self.assertEqual(SportsBaseYouTubeUpload.objects.count(), 1)

    def test_valid_result_links_video_to_match(self):
        upload = claim_next_youtube_upload()
        finished = apply_youtube_upload_result(
            upload,
            {
                "status": "uploaded",
                "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                "youtube_video_id": "abcdefghijk",
                "content_sha256": "a" * 64,
                "file_size_bytes": 31_000_000,
            },
        )
        self.assertEqual(finished.status, SportsBaseYouTubeUpload.Status.UPLOADED)
        self.assertEqual(finished.match, self.match)
        self.assertEqual(finished.youtube_video_id, "abcdefghijk")

    def test_disabled_subscription_does_not_queue_upload(self):
        self.subscription.youtube_delivery_enabled = False
        self.subscription.save(update_fields=("youtube_delivery_enabled", "updated_at"))
        self.assertEqual(ensure_youtube_upload_jobs(), 0)
        self.assertFalse(SportsBaseYouTubeUpload.objects.exists())


class YouTubeUploaderPathTests(TestCase):
    def test_local_video_is_resolved_inside_subscription_storage(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            match_folder = root / "player_1" / "match_1"
            match_folder.mkdir(parents=True)
            video = match_folder / "actions.mp4"
            video.write_bytes(b"video")
            uploader = YouTubeStudioUploader(root)
            resolved = uploader.resolve_video_path(
                {
                    "match": {
                        "local_folder_key": r"player_1\match_1",
                        "filename": "actions.mp4",
                    }
                }
            )
            self.assertEqual(resolved, video.resolve())

    def test_path_traversal_is_rejected(self):
        with TemporaryDirectory() as directory:
            uploader = YouTubeStudioUploader(directory)
            with self.assertRaises(YouTubeUploadError):
                uploader.resolve_video_path(
                    {
                        "match": {
                            "local_folder_key": "../outside",
                            "filename": "actions.mp4",
                        }
                    }
                )

    def test_local_receipt_prevents_duplicate_upload_after_network_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            match_folder = root / "player_1" / "match_1"
            match_folder.mkdir(parents=True)
            video = match_folder / "actions.mp4"
            video.write_bytes(b"same-video-content")
            uploader = YouTubeStudioUploader(root)
            job = {
                "job_id": 91,
                "match": {
                    "local_folder_key": "player_1/match_1",
                    "filename": "actions.mp4",
                },
            }
            digest = "9f49d074192c1a27e5317cae42d054485229606a4bd0fc3592a6c0238716d5d1"
            receipt = {
                "status": "uploaded",
                "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                "youtube_video_id": "abcdefghijk",
                "content_sha256": digest,
                "file_size_bytes": video.stat().st_size,
            }
            uploader._save_receipt(job, receipt)
            self.assertEqual(
                uploader._load_receipt(
                    job,
                    content_sha256=digest,
                    file_size=video.stat().st_size,
                ),
                receipt,
            )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_SITE_URL="https://example.test",
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
)
class PerformanceReportTests(SportsBaseFixtureMixin, TestCase):
    def _create_match(self, number, pass_rate=85):
        match = SportsBaseMatch.objects.create(
            subscription=self.subscription,
            sportsbase_match_id=str(990000 + number),
            season=self.subscription.season,
            match_date=timezone.localdate() - timedelta(days=6 - number),
            home_team="Stade Tunisien",
            away_team=f"Club {number}",
            sync_state=SportsBaseMatch.SyncState.SYNCED,
            actions_state=SportsBaseMatch.ActionsState.DOWNLOADED,
            local_folder_key=f"player/match_{number}",
            all_actions_filename=f"actions-{number}.mp4",
        )
        SportsBaseMatchStats.objects.create(
            match=match,
            minutes_played=90,
            detailed_statistics={
                "Passes": 40 + number,
                "Passes accurate, %": f"{pass_rate}%",
                "Challenges": 8,
                "Challenges won, %": "62%",
            },
        )
        return match

    def test_match_and_five_match_cycle_reports_are_generated_once(self):
        matches = [self._create_match(number) for number in range(1, 6)]
        generated = generate_reports_for_subscription(self.subscription)
        self.assertEqual(len(generated), 6)
        self.assertEqual(
            PerformanceReport.objects.filter(
                report_type=PerformanceReport.ReportType.MATCH
            ).count(),
            5,
        )
        cycle = PerformanceReport.objects.get(
            report_type=PerformanceReport.ReportType.CYCLE
        )
        self.assertEqual(cycle.match_ids, [item.sportsbase_match_id for item in matches])
        generate_reports_for_subscription(self.subscription)
        self.assertEqual(PerformanceReport.objects.count(), 6)

    def test_manual_analysis_is_not_overwritten_by_next_sync(self):
        match = self._create_match(1)
        report = generate_match_report(match)
        report.strengths = "Observation personnelle de l’analyste."
        report.is_manually_edited = True
        report.save(update_fields=("strengths", "is_manually_edited", "updated_at"))
        generate_match_report(match)
        report.refresh_from_db()
        self.assertEqual(report.strengths, "Observation personnelle de l’analyste.")

    def test_pdf_is_generated_from_current_report_version(self):
        report = generate_match_report(self._create_match(1))
        report.analyst_notes = "Conserver cette observation dans le PDF."
        report.save(update_fields=("analyst_notes", "updated_at"))
        pdf = render_report_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        self.client.force_login(self.admin)
        agent_pdf = self.client.get(
            reverse("performance:api_report_pdf", args=(report.pk,))
        )
        self.assertEqual(agent_pdf.status_code, 200)
        self.assertEqual(agent_pdf["Content-Type"], "application/pdf")
        self.assertIn("attachment", agent_pdf["Content-Disposition"])

    def test_email_waits_for_video_and_published_report(self):
        match = self._create_match(1)
        report = generate_match_report(match)
        upload = SportsBaseYouTubeUpload.objects.create(
            match=match,
            status=SportsBaseYouTubeUpload.Status.UPLOADED,
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            youtube_video_id="abcdefghijk",
        )
        self.assertTrue(send_ready_delivery_notification(upload))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(upload.youtube_url, mail.outbox[0].body)
        self.assertIn(reverse("performance:report_pdf", args=(report.pk,)), mail.outbox[0].body)
        self.assertFalse(send_ready_delivery_notification(upload))
        self.assertEqual(len(mail.outbox), 1)

    def test_portal_shows_embedded_video_and_dynamic_report(self):
        match = self._create_match(1)
        report = generate_match_report(match)
        report.analysis_payload = {
            "available": True,
            "player": {"profile_score": 78},
            "verdict": {
                "score": 82,
                "label": "TRÈS BON MATCH",
                "tone": "excellent",
            },
            "appendix_metrics": [
                {"metric": "Goals", "display": "1"},
                {"metric": "Assists", "display": "0"},
                {"metric": "Key passes", "display": "3"},
            ],
        }
        report.save(update_fields=("analysis_payload", "updated_at"))
        SportsBaseYouTubeUpload.objects.create(
            match=match,
            status=SportsBaseYouTubeUpload.Status.UPLOADED,
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            youtube_video_id="abcdefghijk",
        )
        user = self.portal_user("report-client")
        PlayerAccess.objects.create(user=user, player=self.player)
        self.client.force_login(user)
        detail = self.client.get(
            reverse(
                "performance:portal_match",
                args=(self.player.pk, match.sportsbase_match_id),
            )
        )
        self.assertContains(detail, "youtube-nocookie.com/embed/abcdefghijk")
        self.assertContains(detail, "Rapport de l’analyste")
        self.assertContains(detail, "MS Score")
        self.assertContains(detail, "TRÈS BON MATCH")
        self.assertContains(detail, "Passes clés")
        pdf = self.client.get(reverse("performance:report_pdf", args=(report.pk,)))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_subscription_controls_report_but_account_controls_portal_copy(self):
        self.subscription.report_language = SportsBaseSubscription.ReportLanguage.ENGLISH
        self.subscription.save(update_fields=("report_language", "updated_at"))
        match = self._create_match(1)
        report = generate_match_report(match)
        self.assertEqual(report.language, "en")
        self.assertTrue(report.title.startswith("Performance report"))
        user = self.portal_user("english-client")
        user.portal_profile.preferred_language = "ar"
        user.portal_profile.save(update_fields=("preferred_language", "updated_at"))
        PlayerAccess.objects.create(user=user, player=self.player)
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "performance:portal_match",
                args=(self.player.pk, match.sportsbase_match_id),
            )
        )
        self.assertContains(response, "تحليل المباراة")
        self.assertNotContains(response, "Analyse du match")
        self.assertNotContains(response, "Match analysis")
