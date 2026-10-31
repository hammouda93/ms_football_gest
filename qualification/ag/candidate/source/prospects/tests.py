from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestion_joueurs.models import Invoice, Payment, Player, Video

from .forms import ProspectRequestForm
from .models import Prospect


class ProspectFeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.superuser = user_model.objects.create_superuser(
            username="admin-prospects",
            email="admin@example.com",
            password="test-password",
        )
        cls.regular_user = user_model.objects.create_user(
            username="editor-prospects",
            password="test-password",
        )
        cls.prospect = Prospect.objects.create(
            full_name="Joueur Test",
            transfermarkt_url=(
                "https://www.transfermarkt.fr/joueur-test/profil/spieler/123"
            ),
            date_of_birth=date(2000, 1, 2),
            whatsapp_number="+21620123456",
            email="joueur@example.com",
            country="Tunisie",
            club="Club Test",
            league=Prospect.League.TUNISIA_L1,
            position=Prospect.Position.MIDFIELDER,
            season="2025/2026",
            service_type=Prospect.Service.HIGHLIGHTS,
            match_links="https://example.com/match-1",
        )

    @staticmethod
    def valid_form_data():
        return {
            "transfermarkt_url": (
                "https://www.transfermarkt.fr/nouveau-joueur/profil/spieler/456"
            ),
            "full_name": "Nouveau Joueur",
            "date_of_birth": "2001-03-04",
            "whatsapp_number": "+216 22 345 678",
            "email": "nouveau@example.com",
            "country": "Tunisie",
            "club": "Avenir Sportif",
            "league": Prospect.League.TUNISIA_L2,
            "position": Prospect.Position.FORWARD,
            "season": "2025/2026",
            "service_type": Prospect.Service.VIDEO_CV,
            "match_links": (
                "https://example.com/match-1\n"
                "https://example.com/match-2"
            ),
            "desired_deadline": (date.today() + timedelta(days=14)).isoformat(),
            "message": "Je souhaite une vidéo dynamique.",
        }

    def test_public_form_is_available(self):
        response = self.client.get(reverse("prospects:request_create"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "prospects/request_form.html")
        self.assertContains(response, 'id="importTransfermarktBtn"')
        self.assertContains(response, 'id="id_transfermarkt_url"')

    @patch("prospects.views.parse_transfermarkt_player")
    def test_transfermarkt_import_prefills_editable_data_without_creating_records(
        self,
        parse_transfermarkt_player,
    ):
        parse_transfermarkt_player.return_value = {
            "name": "Joueur Importé",
            "date_of_birth": "1999-05-06",
            "club": "Club Importé",
            "league": "L1",
            "position": "MF",
        }
        prospect_count = Prospect.objects.count()
        player_count = Player.objects.count()
        url = "https://www.transfermarkt.fr/joueur/profil/spieler/999"

        response = self.client.post(
            reverse("prospects:transfermarkt_import"),
            data={"url": url},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["player"]["name"], "Joueur Importé")
        self.assertEqual(payload["player"]["date_of_birth"], "1999-05-06")
        self.assertEqual(payload["player"]["league"], Prospect.League.TUNISIA_L1)
        self.assertEqual(
            payload["player"]["position"],
            Prospect.Position.MIDFIELDER,
        )
        self.assertEqual(payload["player"]["transfermarkt_url"], url)
        parse_transfermarkt_player.assert_called_once_with(url)
        self.assertEqual(Prospect.objects.count(), prospect_count)
        self.assertEqual(Player.objects.count(), player_count)

    @patch("prospects.views.parse_transfermarkt_player")
    def test_transfermarkt_import_rejects_non_transfermarkt_hosts(
        self,
        parse_transfermarkt_player,
    ):
        response = self.client.post(
            reverse("prospects:transfermarkt_import"),
            data={"url": "https://transfermarkt.example.com/faux-profil"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        parse_transfermarkt_player.assert_not_called()

    def test_valid_public_submission_creates_only_a_prospect(self):
        prospect_count = Prospect.objects.count()
        protected_counts = {
            Player: Player.objects.count(),
            Video: Video.objects.count(),
            Invoice: Invoice.objects.count(),
            Payment: Payment.objects.count(),
        }
        submitted_data = self.valid_form_data()
        submitted_data.update(
            {
                "status": Prospect.Status.CONVERTED,
                "internal_notes": "Cette valeur publique doit être ignorée.",
                "source": "Valeur injectée",
            }
        )

        response = self.client.post(
            reverse("prospects:request_create"),
            data=submitted_data,
        )

        self.assertRedirects(response, reverse("prospects:request_success"))
        self.assertEqual(Prospect.objects.count(), prospect_count + 1)
        created = Prospect.objects.get(full_name="Nouveau Joueur")
        self.assertEqual(created.status, Prospect.Status.NEW)
        self.assertEqual(created.whatsapp_number, "+21622345678")
        self.assertEqual(created.date_of_birth, date(2001, 3, 4))
        self.assertEqual(created.league, Prospect.League.TUNISIA_L2)
        self.assertEqual(
            created.transfermarkt_url,
            submitted_data["transfermarkt_url"],
        )
        self.assertEqual(created.internal_notes, "")
        self.assertEqual(created.source, "Formulaire web")
        for model, initial_count in protected_counts.items():
            self.assertEqual(model.objects.count(), initial_count)

    def test_match_links_must_be_http_or_https_urls(self):
        data = self.valid_form_data()
        data["match_links"] = "ceci-n-est-pas-un-lien"

        form = ProspectRequestForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("match_links", form.errors)

    def test_transfermarkt_makes_country_and_match_links_optional(self):
        data = self.valid_form_data()
        data.update(
            {
                "full_name": "Joueur Sans Liens",
                "country": "",
                "match_links": "",
            }
        )

        response = self.client.post(
            reverse("prospects:request_create"),
            data=data,
        )

        self.assertRedirects(response, reverse("prospects:request_success"))
        prospect = Prospect.objects.get(full_name="Joueur Sans Liens")
        self.assertEqual(prospect.country, "")
        self.assertEqual(prospect.match_links, "")
        self.assertTrue(prospect.transfermarkt_url)

    def test_match_links_are_required_without_transfermarkt(self):
        data = self.valid_form_data()
        data.update({"transfermarkt_url": "", "match_links": ""})

        form = ProspectRequestForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("match_links", form.errors)
        self.assertIn("Transfermarkt", form.errors["match_links"][0])

    def test_past_deadline_is_rejected(self):
        data = self.valid_form_data()
        data["desired_deadline"] = (date.today() - timedelta(days=1)).isoformat()

        form = ProspectRequestForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("desired_deadline", form.errors)

    def test_anonymous_user_is_redirected_to_login_for_internal_list(self):
        response = self.client.get(reverse("prospects:prospect_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("user_login"), response.url)

    def test_authenticated_non_superuser_is_forbidden(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("prospects:prospect_list"))

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_view_internal_list(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("prospects:prospect_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.prospect.full_name)
        self.assertContains(response, "Gestion des Prospects")
        self.assertContains(response, "Démarrer sur WhatsApp")

    def test_superuser_can_edit_a_prospect(self):
        self.client.force_login(self.superuser)
        data = self.valid_form_data()
        data.update(
            {
                "full_name": "Joueur Corrigé",
                "status": Prospect.Status.INTERESTED,
                "internal_notes": "À rappeler vendredi.",
            }
        )

        response = self.client.post(
            reverse("prospects:prospect_edit", kwargs={"pk": self.prospect.pk}),
            data=data,
        )

        self.assertRedirects(response, reverse("prospects:prospect_list"))
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.full_name, "Joueur Corrigé")
        self.assertEqual(self.prospect.status, Prospect.Status.INTERESTED)
        self.assertEqual(self.prospect.internal_notes, "À rappeler vendredi.")

    def test_status_update_is_post_only(self):
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse(
                "prospects:prospect_status_update",
                kwargs={"pk": self.prospect.pk},
            )
        )

        self.assertEqual(response.status_code, 405)

    def test_non_superuser_cannot_update_a_status(self):
        self.client.force_login(self.regular_user)

        response = self.client.post(
            reverse(
                "prospects:prospect_status_update",
                kwargs={"pk": self.prospect.pk},
            ),
            data={"status": Prospect.Status.CONVERTED},
        )

        self.assertEqual(response.status_code, 403)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.status, Prospect.Status.NEW)

    def test_invalid_status_is_ignored(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse(
                "prospects:prospect_status_update",
                kwargs={"pk": self.prospect.pk},
            ),
            data={"status": "unknown-status"},
        )

        self.assertRedirects(response, reverse("prospects:prospect_list"))
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.status, Prospect.Status.NEW)

    def test_converting_a_prospect_only_changes_its_status(self):
        self.client.force_login(self.superuser)
        protected_counts = {
            Player: Player.objects.count(),
            Video: Video.objects.count(),
            Invoice: Invoice.objects.count(),
            Payment: Payment.objects.count(),
        }

        response = self.client.post(
            reverse(
                "prospects:prospect_status_update",
                kwargs={"pk": self.prospect.pk},
            ),
            data={"status": Prospect.Status.CONVERTED},
        )

        self.assertRedirects(response, reverse("prospects:prospect_list"))
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.status, Prospect.Status.CONVERTED)
        for model, initial_count in protected_counts.items():
            self.assertEqual(model.objects.count(), initial_count)

    def test_whatsapp_link_contains_phone_and_prefilled_message(self):
        self.assertIn("wa.me/21620123456", self.prospect.whatsapp_url)
        self.assertIn("Joueur%20Test", self.prospect.whatsapp_url)

    def test_conversion_creates_player_without_video_or_financial_records(self):
        self.client.force_login(self.superuser)
        initial_counts = {
            Player: Player.objects.count(),
            Video: Video.objects.count(),
            Invoice: Invoice.objects.count(),
            Payment: Payment.objects.count(),
        }

        response = self.client.post(
            reverse("prospects:prospect_convert", kwargs={"pk": self.prospect.pk})
        )

        player = Player.objects.get(name=self.prospect.full_name)
        self.assertEqual(
            response.url,
            f"{reverse('create_video_request')}?player_id={player.pk}",
        )
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.status, Prospect.Status.CONVERTED)
        self.assertEqual(self.prospect.player, player)
        self.assertEqual(player.date_of_birth, self.prospect.date_of_birth)
        self.assertEqual(player.club, self.prospect.club)
        self.assertEqual(player.email, self.prospect.email)
        self.assertEqual(player.whatsapp_number, self.prospect.whatsapp_number)
        self.assertEqual(player.league, self.prospect.league)
        self.assertEqual(player.position, "MF")
        self.assertEqual(player.transfermarkt_url, self.prospect.transfermarkt_url)
        self.assertEqual(Player.objects.count(), initial_counts[Player] + 1)
        for model in (Video, Invoice, Payment):
            self.assertEqual(model.objects.count(), initial_counts[model])

    def test_conversion_reuses_player_with_same_transfermarkt_url(self):
        existing_player = Player.objects.create(
            name="Nom déjà enregistré",
            club="",
            email="",
            whatsapp_number=None,
            transfermarkt_url=self.prospect.transfermarkt_url,
        )
        self.client.force_login(self.superuser)
        player_count = Player.objects.count()

        response = self.client.post(
            reverse("prospects:prospect_convert", kwargs={"pk": self.prospect.pk})
        )

        self.assertEqual(response.status_code, 302)
        self.prospect.refresh_from_db()
        existing_player.refresh_from_db()
        self.assertEqual(Player.objects.count(), player_count)
        self.assertEqual(self.prospect.player, existing_player)
        self.assertEqual(existing_player.email, self.prospect.email)
        self.assertEqual(
            existing_player.whatsapp_number,
            self.prospect.whatsapp_number,
        )

    def test_converted_player_is_preselected_on_create_video_page(self):
        player = Player.objects.create(
            name="Joueur Sélectionné",
            club="Club",
            email="selection@example.com",
        )
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("create_video_request"),
            data={"player_id": player.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["new_player_added"])
        self.assertEqual(response.context["added_player"], player)
        self.assertContains(response, f"Ajouter une Vidéo pour {player.name}")

    def test_whatsapp_start_marks_new_prospect_as_contacted(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse(
                "prospects:prospect_whatsapp_start",
                kwargs={"pk": self.prospect.pk},
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://wa.me/"))
        decoded_url = unquote(response["Location"])
        self.assertIn("Moi, c’est Moataz", decoded_url)
        self.assertIn("5 meilleurs matchs", decoded_url)
        self.assertIn("actions individuelles", decoded_url)
        self.prospect.refresh_from_db()
        self.assertEqual(self.prospect.status, Prospect.Status.CONTACTED)

    def test_deleting_prospect_keeps_linked_player(self):
        player = Player.objects.create(
            name="Joueur conservé",
            club="Club",
            email="conserve@example.com",
        )
        self.prospect.player = player
        self.prospect.save(update_fields=("player", "updated_at"))
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("prospects:prospect_delete", kwargs={"pk": self.prospect.pk})
        )

        self.assertRedirects(response, reverse("prospects:prospect_list"))
        self.assertFalse(Prospect.objects.filter(pk=self.prospect.pk).exists())
        self.assertTrue(Player.objects.filter(pk=player.pk).exists())

    def test_sensitive_actions_are_post_only(self):
        self.client.force_login(self.superuser)
        route_names = (
            "prospects:prospect_delete",
            "prospects:prospect_convert",
            "prospects:prospect_whatsapp_start",
        )

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(route_name, kwargs={"pk": self.prospect.pk})
                )
                self.assertEqual(response.status_code, 405)

    def test_non_superuser_cannot_manage_prospect(self):
        self.client.force_login(self.regular_user)
        requests = (
            ("get", "prospects:prospect_edit"),
            ("post", "prospects:prospect_delete"),
            ("post", "prospects:prospect_convert"),
            ("post", "prospects:prospect_whatsapp_start"),
        )

        for method, route_name in requests:
            with self.subTest(route_name=route_name):
                response = getattr(self.client, method)(
                    reverse(route_name, kwargs={"pk": self.prospect.pk})
                )
                self.assertEqual(response.status_code, 403)
