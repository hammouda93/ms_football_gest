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

    def test_full_player_record_amend_changes_many_fields_at_once(self):
        adapter = SIMPLE["player.record.amend"]
        values = {
            "id": self.player.pk,
            "name": "Updated Player",
            "club": "Updated Club",
            "league": "OC",
            "position": "MF",
            "email": "updated@example.invalid",
            "sportsbase_url": "https://sportsbase.example/player/48",
            "transfermarkt_url": "https://www.transfermarkt.com/sample/profil/spieler/48",
            "client_fidel": True,
            "client_vip": True,
        }
        preview = adapter.preview({
            "as": "profile", "op": "player.record.amend", "values": values,
        }, self.owner.pk)
        self.assertEqual(preview["old"]["club"], "Old FC")
        self.assertEqual(preview["new"]["club"], "Updated Club")
        self.player.refresh_from_db()
        self.assertEqual(self.player.club, "Old FC")
        adapter.apply(values, self.owner.pk)
        self.player.refresh_from_db()
        self.assertEqual(self.player.name, "Updated Player")
        self.assertEqual(self.player.club, "Updated Club")
        self.assertEqual(self.player.email, "updated@example.invalid")
        self.assertTrue(self.player.client_vip)
        self.assertTrue(self.player.client_fidel)
        self.assertEqual(
            self.player.transfermarkt_url,
            "https://www.transfermarkt.com/sample/profil/spieler/48",
        )

    def test_player_organization_unlink_closes_only_one_membership(self):
        from client_portal.models import Organization, OrganizationPlayer
        organization = Organization.objects.create(
            name="First Academy", kind=Organization.Kind.ACADEMY,
            created_by=self.owner, is_active=True,
        )
        other_organization = Organization.objects.create(
            name="Second Academy", kind=Organization.Kind.ACADEMY,
            created_by=self.owner, is_active=True,
        )
        link = OrganizationPlayer.objects.create(
            organization=organization, player=self.player,
            added_by=self.owner, is_active=True,
        )
        other_link = OrganizationPlayer.objects.create(
            organization=other_organization, player=self.player,
            added_by=self.owner, is_active=True,
        )
        adapter = SIMPLE["player.organization.unlink"]
        before = adapter.preview({
            "as": "unlink", "op": "player.organization.unlink",
            "values": {"id": link.pk},
        }, self.owner.pk)
        self.assertEqual(before["player"]["id"], self.player.pk)
        self.assertTrue(before["old"]["is_active"])
        link.refresh_from_db()
        self.assertTrue(link.is_active)
        lookup = adapter.lookup("Existing", 10, self.owner.pk)
        self.assertEqual(len(lookup["rows"]), 2)
        adapter.apply({"id": link.pk}, self.owner.pk)
        link.refresh_from_db()
        other_link.refresh_from_db()
        self.assertFalse(link.is_active)
        self.assertIsNotNone(link.ended_at)
        self.assertTrue(other_link.is_active)
        self.assertIsNone(other_link.ended_at)
        self.assertTrue(Player.objects.filter(pk=self.player.pk).exists())
        with self.assertRaises(ValueError):
            adapter.apply({"id": link.pk}, self.owner.pk)

    def test_player_organization_unlink_rejects_non_superuser(self):
        from client_portal.models import Organization, OrganizationPlayer
        organization = Organization.objects.create(
            name="Test Academy", kind=Organization.Kind.ACADEMY,
            created_by=self.owner, is_active=True,
        )
        link = OrganizationPlayer.objects.create(
            organization=organization, player=self.player,
            is_active=True,
        )
        standard = get_user_model().objects.create_user(
            username="ordinary", password="test-only-password",
        )
        with self.assertRaises(PermissionError):
            SIMPLE["player.organization.unlink"].cleaned(
                {"id": link.pk}, standard.pk,
            )
        link.refresh_from_db()
        self.assertTrue(link.is_active)

    def test_new_membership_without_video_pack_and_safe_reactivation(self):
        from client_portal.models import Organization, OrganizationPlayer
        organization = Organization.objects.create(
            name="Academy New", kind=Organization.Kind.ACADEMY,
            created_by=self.owner, is_active=True,
        )
        adapter = SIMPLE["player.organization.link"]
        values = {"player": self.player.pk, "organization": organization.pk}
        preview = adapter.preview({
            "as": "new_link", "op": "player.organization.link", "values": values,
        }, self.owner.pk)
        self.assertIsNone(preview["old"])
        self.assertIsNone(preview["new"]["expected_matches"])
        self.assertFalse(OrganizationPlayer.objects.filter(
            player=self.player, organization=organization,
        ).exists())
        link = adapter.apply(values, self.owner.pk)
        self.assertTrue(link.is_active)
        self.assertIsNone(link.expected_matches)
        self.assertEqual(link.organization_id, organization.pk)
        with self.assertRaises(ValueError):
            adapter.cleaned(values, self.owner.pk)
        SIMPLE["player.organization.unlink"].apply(
            {"id": link.pk}, self.owner.pk,
        )
        link.refresh_from_db()
        self.assertFalse(link.is_active)
        reactivated = adapter.apply({
            **values, "label": "Return to Academy", "expected_matches": 5,
        }, self.owner.pk)
        link.refresh_from_db()
        self.assertEqual(reactivated.pk, link.pk)
        self.assertTrue(link.is_active)
        self.assertIsNone(link.ended_at)
        self.assertEqual(link.label, "Return to Academy")
        self.assertEqual(link.expected_matches, 5)

    def test_link_requires_valid_organization_and_refuses_invalid_pack(self):
        from client_portal.models import Organization, OrganizationPlayer
        organization = Organization.objects.create(
            name="Inactive Academy", kind=Organization.Kind.ACADEMY,
            created_by=self.owner, is_active=False,
        )
        adapter = SIMPLE["player.organization.link"]
        with self.assertRaises(ValueError):
            adapter.cleaned({
                "player": self.player.pk, "organization": organization.pk,
            }, self.owner.pk)
        organization.is_active = True
        organization.save(update_fields=["is_active"])
        with self.assertRaises(ValueError):
            adapter.cleaned({
                "player": self.player.pk, "organization": organization.pk,
                "expected_matches": 7,
            }, self.owner.pk)
        self.assertFalse(OrganizationPlayer.objects.filter(
            player=self.player, organization=organization,
        ).exists())
