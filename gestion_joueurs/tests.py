from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Invoice, Notification, Player, Video, VideoEditor
from .utils import set_current_user
from .video_status_whatsapp import (
    NOTIFICATION_PAYMENT_MODES,
    build_notification_whatsapp_url,
    build_status_notification_context,
    get_payment_snapshot,
)


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
