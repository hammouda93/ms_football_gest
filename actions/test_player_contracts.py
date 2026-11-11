"""Regression tests for expanded Hermes PlayerForm parity contracts.

No actual native approval, production credentials or Heroku services are exercised.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from gestion_joueurs.models import Player
from .registry import SIMPLE, catalogue


class PlayerParityContractTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(
            username="hermes-player-test", email="owner@example.invalid",
            password="test-only-password",
        )
        self.player = Player.objects.create(
            name="Existing Player", club="Old FC", league="L1",
            position="DF", date_of_birth=date(2003, 1, 2),
        )

    def test_registry_and_schema_expose_exact_reviewed_player_fields(self):
        contracts = catalogue()
        sources = contracts["player.sources.amend"]
        full = contracts["player.record.create"]
        self.assertEqual(
            sources["fields"],
            ["id", "sportsbase_url", "transfermarkt_url"],
        )
        self.assertEqual(
            set(full["fields"]),
            {
                "name", "date_of_birth", "club", "league", "position",
                "email", "whatsapp_number", "sportsbase_url",
                "transfermarkt_url", "client_fidel", "client_vip",
            },
        )
        self.assertNotIn("create_client_account", full["fields"])
        self.assertNotIn("organization", full["fields"])
        self.assertIn("accounts", full["excludedEffects"])
        self.assertIn("access", sources["excludedEffects"])
        self.assertIn("player.profile.create", contracts)
        self.assertIn("player.business.amend", contracts)

    def test_sources_preview_and_apply_preserve_unselected_fields(self):
        adapter = SIMPLE["player.sources.amend"]
        changes = {
            "id": self.player.pk,
            "sportsbase_url": "https://sportsbase.example/footballer/42",
            "transfermarkt_url": "https://www.transfermarkt.com/example/profil/spieler/42",
        }
        preview = adapter.preview({
            "as": "sources", "op": "player.sources.amend", "values": changes,
        }, self.owner.pk)
        self.player.refresh_from_db()
        self.assertFalse(self.player.sportsbase_url)
        self.assertEqual(preview["new"]["sportsbase_url"], changes["sportsbase_url"])
        self.assertEqual(preview["old"]["sportsbase_url"], self.player.sportsbase_url)
        adapter.apply(changes, self.owner.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.sportsbase_url, changes["sportsbase_url"])
        self.assertEqual(self.player.transfermarkt_url, changes["transfermarkt_url"])
        self.assertEqual(self.player.club, "Old FC")
        self.assertEqual(self.player.name, "Existing Player")

    def test_sources_require_valid_urls_and_active_superuser(self):
        adapter = SIMPLE["player.sources.amend"]
        with self.assertRaises(ValueError):
            adapter.cleaned({
                "id": self.player.pk, "sportsbase_url": "not a valid URL",
            }, self.owner.pk)
        self.player.refresh_from_db()
        self.assertFalse(self.player.sportsbase_url)
        standard = get_user_model().objects.create_user(
            username="unprivileged", password="test-only-password",
        )
        with self.assertRaises(PermissionError):
            adapter.cleaned({
                "id": self.player.pk,
                "sportsbase_url": "https://sportsbase.example/footballer/42",
            }, standard.pk)

    def test_full_player_creation_persists_reviewed_fields_only(self):
        adapter = SIMPLE["player.record.create"]
        values = {
            "name": "Complete Player",
            "date_of_birth": "2002-02-01",
            "club": "New Club",
            "league": "OC",
            "position": "MF",
            "email": "player@example.invalid",
            "whatsapp_number": "+21612345678",
            "sportsbase_url": "https://sportsbase.example/footballer/123",
            "transfermarkt_url": "https://www.transfermarkt.com/sample/profil/spieler/123",
            "client_fidel": True,
            "client_vip": False,
        }
        before = Player.objects.count()
        preview = adapter.preview({
            "as": "new_player", "op": "player.record.create", "values": values,
        }, self.owner.pk)
        self.assertIsNone(preview["id"])
        self.assertEqual(Player.objects.count(), before)
        created = adapter.apply(values, self.owner.pk)
        self.assertEqual(Player.objects.count(), before + 1)
        self.assertEqual(created.email, "player@example.invalid")
        self.assertEqual(created.sportsbase_url, values["sportsbase_url"])
        self.assertEqual(created.transfermarkt_url, values["transfermarkt_url"])
        self.assertTrue(created.client_fidel)
        self.assertEqual(created.date_of_birth, date(2002, 2, 1))
        self.assertFalse(created.portal_organization_links.exists())
        with self.assertRaises(ValueError):
            adapter.apply(values, self.owner.pk)

    def test_existing_player_contracts_stay_separate(self):
        self.assertEqual(
            SIMPLE["player.business.amend"].fields,
            ("email", "whatsapp_number", "client_fidel", "client_vip"),
        )
        self.assertEqual(
            SIMPLE["player.profile.amend"].fields,
            ("name", "date_of_birth", "club", "league", "position", "whatsapp_number"),
        )
