import base64
from datetime import timedelta

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
from .models import (
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
)
from .scraper import SportsBaseSubscriptionScraper
from .services import apply_sync_result, claim_next_job, queue_sync


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
    def test_job_payload_contains_only_operational_player_data(self):
        job, created = queue_sync(self.subscription, requested_by=self.admin)
        self.assertTrue(created)
        claimed = claim_next_job()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.payload["player"]["id"], self.player.pk)
        self.assertEqual(claimed.payload["season"], "2025/2026")
        self.assertNotIn("password", claimed.payload)

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


class ScraperNormalizationTests(TestCase):
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
