from datetime import date, timedelta

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
            whatsapp_number="+21620123456",
            email="joueur@example.com",
            country="Tunisie",
            club="Club Test",
            position=Prospect.Position.MIDFIELDER,
            season="2025/2026",
            service_type=Prospect.Service.HIGHLIGHTS,
            match_links="https://example.com/match-1",
        )

    @staticmethod
    def valid_form_data():
        return {
            "full_name": "Nouveau Joueur",
            "whatsapp_number": "+216 22 345 678",
            "email": "nouveau@example.com",
            "country": "Tunisie",
            "club": "Avenir Sportif",
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
