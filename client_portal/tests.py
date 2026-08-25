from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestion_joueurs.models import Invoice, Payment, Player, Video, VideoEditor
from gestion_joueurs.utils import set_current_user

from .models import (
    AgentPlayerRequest,
    CommunicationLog,
    MediaSubmission,
    Organization,
    OrganizationMembership,
    OrganizationPlayer,
    PaymentRequest,
    PlayerAccess,
    PortalAccessLink,
    PortalProfile,
    RevisionRequest,
    VideoActivity,
    VideoVersion,
    VideoWorkflow,
)
from .services import create_portal_account


class PortalFixtureMixin:
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="portal-admin",
            email="admin@example.com",
            password="test-password",
        )
        set_current_user(self.admin)
        self.editor_user = User.objects.create_user(
            username="portal-editor",
            password="test-password",
        )
        self.other_editor_user = User.objects.create_user(
            username="other-editor",
            password="test-password",
        )
        self.editor = VideoEditor.objects.create(user=self.editor_user)
        self.other_editor = VideoEditor.objects.create(user=self.other_editor_user)
        self.player = Player.objects.create(
            name="Alpha Player",
            club="Club Alpha",
            email="alpha@example.com",
            whatsapp_number="+21620111222",
            league="L1",
            position="MF",
        )
        self.second_player = Player.objects.create(
            name="Beta Player",
            club="Club Beta",
            email="beta@example.com",
            whatsapp_number="+21620333444",
            league="L2",
            position="DF",
        )
        self.hidden_player = Player.objects.create(
            name="Hidden Player",
            club="Hidden Club",
            email="hidden@example.com",
            league="OC",
            position="FW",
        )
        deadline = timezone.localdate() + timedelta(days=14)
        self.video = Video.objects.create(
            player=self.player,
            editor=self.editor,
            status=Video.StatusChoices.PENDING,
            advance_payment=Decimal("100"),
            total_payment=Decimal("500"),
            deadline=deadline,
            season="2025/2026",
            club=self.player.club,
            league=self.player.league,
        )
        self.second_video = Video.objects.create(
            player=self.second_player,
            editor=self.editor,
            status=Video.StatusChoices.IN_PROGRESS,
            advance_payment=Decimal("200"),
            total_payment=Decimal("600"),
            deadline=deadline,
            season="2025/2026",
            club=self.second_player.club,
            league=self.second_player.league,
        )
        self.hidden_video = Video.objects.create(
            player=self.hidden_player,
            editor=self.other_editor,
            status=Video.StatusChoices.IN_PROGRESS,
            advance_payment=Decimal("0"),
            total_payment=Decimal("700"),
            deadline=deadline,
            season="2025/2026",
            club=self.hidden_player.club,
            league=self.hidden_player.league,
        )
        self.invoice = Invoice.objects.create(
            video=self.video,
            total_amount=Decimal("500"),
            amount_paid=Decimal("100"),
            status="partially_paid",
            created_by=self.admin,
        )

    def make_portal_user(self, username, account_type=PortalProfile.AccountType.PLAYER):
        user = User.objects.create_user(username=username, email=f"{username}@example.com")
        PortalProfile.objects.create(
            user=user,
            account_type=account_type,
            display_name=username.title(),
            created_by=self.admin,
        )
        return user


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class ProductionCenterTests(PortalFixtureMixin, TestCase):
    def test_board_requires_internal_account(self):
        response = self.client.get(reverse("portal:production_board"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("user_login"), response.url)

    def test_editor_sees_only_assigned_videos(self):
        self.client.force_login(self.editor_user)
        response = self.client.get(reverse("portal:production_board"))
        self.assertContains(response, self.player.name)
        self.assertContains(response, self.second_player.name)
        self.assertNotContains(response, self.hidden_player.name)

    def test_board_get_is_read_only_for_existing_records(self):
        self.client.force_login(self.admin)
        player_snapshot = (self.player.name, self.player.club, self.player.email)
        video_snapshot = (self.video.status, self.video.deadline, self.video.total_payment)
        response = self.client.get(reverse("portal:production_board"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VideoWorkflow.objects.count(), 0)
        self.assertEqual(VideoActivity.objects.count(), 0)
        self.player.refresh_from_db()
        self.video.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            player_snapshot,
        )
        self.assertEqual(
            (self.video.status, self.video.deadline, self.video.total_payment),
            video_snapshot,
        )

    def test_workflow_overlay_does_not_change_video_or_invoice(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal:production_workflow_update", args=(self.video.pk,)),
            {
                "stage": VideoWorkflow.Stage.EDITING,
                "priority": VideoWorkflow.Priority.HIGH,
                "progress": 55,
                "next_action": "Préparer la première version",
                "blocked_reason": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        workflow = VideoWorkflow.objects.get(video=self.video)
        self.assertEqual(workflow.stage, VideoWorkflow.Stage.EDITING)
        self.video.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)
        self.assertEqual(self.invoice.amount_paid, Decimal("100"))
        self.assertTrue(
            VideoActivity.objects.filter(video=self.video, kind="stage").exists()
        )

    def test_blocked_workflow_requires_reason(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("portal:production_workflow_update", args=(self.video.pk,)),
            {
                "stage": VideoWorkflow.Stage.BLOCKED,
                "priority": VideoWorkflow.Priority.URGENT,
                "progress": 20,
                "next_action": "",
                "blocked_reason": "",
            },
        )
        self.assertFalse(VideoWorkflow.objects.filter(video=self.video).exists())

    def test_editor_cannot_open_another_editors_production(self):
        self.client.force_login(self.editor_user)
        response = self.client.get(
            reverse("portal:production_video", args=(self.hidden_video.pk,))
        )
        self.assertEqual(response.status_code, 404)

    def test_internal_production_detail_renders_controls(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("portal:production_video", args=(self.video.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suivi de production")
        self.assertContains(response, "Demande de paiement")
        self.assertContains(response, "WhatsApp")
        self.assertContains(response, "État officiel de la vidéo")
        self.assertContains(
            response,
            reverse("portal:production_video_status_update", args=(self.video.pk,)),
        )
        self.assertNotContains(response, "sticky-panel")

    def test_admin_updates_official_status_from_production_detail(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse(
                "portal:production_video_status_update",
                args=(self.video.pk,),
            ),
            {
                "status": Video.StatusChoices.IN_PROGRESS,
                "video_link": "",
                "notification_action": "skip",
                "payment_message_mode": "auto",
            },
        )

        self.assertRedirects(
            response,
            reverse("portal:production_video", args=(self.video.pk,)),
        )
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.IN_PROGRESS)

    def test_editor_cannot_set_admin_only_delivered_status(self):
        self.client.force_login(self.editor_user)
        response = self.client.post(
            reverse(
                "portal:production_video_status_update",
                args=(self.video.pk,),
            ),
            {
                "status": Video.StatusChoices.DELIVERED,
                "video_link": "https://www.youtube.com/watch?v=abcdefghijk",
                "notification_action": "skip",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)

    def test_delivered_status_can_open_whatsapp_with_final_link(self):
        self.client.force_login(self.admin)
        final_link = "https://www.youtube.com/watch?v=abcdefghijk"
        response = self.client.post(
            reverse(
                "portal:production_video_status_update",
                args=(self.video.pk,),
            ),
            {
                "status": Video.StatusChoices.DELIVERED,
                "video_link": final_link,
                "notification_action": "whatsapp",
                "payment_message_mode": "none",
                "whatsapp_message": "Bonjour, la vidéo est livrée.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://wa.me/21620111222"))
        self.assertIn(final_link, unquote(response.url))
        self.assertTrue(
            CommunicationLog.objects.filter(
                video=self.video,
                channel=CommunicationLog.Channel.WHATSAPP,
                template_key="status_delivered",
            ).exists()
        )
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.DELIVERED)
        self.assertEqual(self.video.video_link, final_link)

    def test_video_orders_distinguish_active_client_space_and_link_dossier(self):
        portal_user = self.make_portal_user("alpha-client-space")
        PlayerAccess.objects.create(
            user=portal_user,
            player=self.player,
            granted_by=self.admin,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Espace actif")
        self.assertContains(
            response,
            reverse("portal:production_video", args=(self.video.pk,)),
        )

        portal_user.portal_profile.is_active = False
        portal_user.portal_profile.save(update_fields=("is_active",))
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Espace désactivé")

    def test_staff_can_publish_version_without_changing_video_status(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal:production_version_add", args=(self.video.pk,)),
            {
                "title": "Première version",
                "preview_url": "https://example.com/preview-v1",
                "final_url": "",
                "notes": "À vérifier",
            },
        )
        self.assertEqual(response.status_code, 302)
        version = VideoVersion.objects.get(video=self.video)
        self.assertEqual(version.version_number, 1)
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)

    def test_whatsapp_action_logs_draft_not_sent(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse(
                "portal:production_whatsapp",
                args=(self.video.pk, "review"),
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("https://wa.me/21620111222"))
        log = CommunicationLog.objects.get(video=self.video)
        self.assertEqual(log.state, CommunicationLog.State.DRAFT_OPENED)

    def test_operations_brief_is_read_only(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("portal:operations_brief"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(VideoWorkflow.objects.count(), 0)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class PortalAccountAndAgentTests(PortalFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(
            name="Elite Agency",
            kind=Organization.Kind.AGENT,
            created_by=self.admin,
        )
        self.agent = self.make_portal_user(
            "elite-agent",
            PortalProfile.AccountType.AGENT,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.agent,
            role=OrganizationMembership.Role.OWNER,
        )
        self.first_link = OrganizationPlayer.objects.create(
            organization=self.organization,
            player=self.player,
            added_by=self.admin,
        )
        OrganizationPlayer.objects.create(
            organization=self.organization,
            player=self.second_player,
            added_by=self.admin,
        )
        self.player_user = self.make_portal_user("alpha-access")
        PlayerAccess.objects.create(
            user=self.player_user,
            player=self.player,
            granted_by=self.admin,
        )

    def test_agent_dashboard_contains_multiple_linked_players_only(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("portal:dashboard"))
        self.assertContains(response, self.player.name)
        self.assertContains(response, self.second_player.name)
        self.assertNotContains(response, self.hidden_player.name)

    def test_player_account_cannot_open_other_player_video(self):
        self.client.force_login(self.player_user)
        allowed = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        forbidden = self.client.get(
            reverse("portal:video", args=(self.second_video.pk,))
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(forbidden.status_code, 404)

    def test_client_video_hides_technical_media_source(self):
        VideoWorkflow.objects.update_or_create(
            video=self.video,
            defaults={
                "stage": VideoWorkflow.Stage.DOWNLOADING,
                "progress": 35,
                "next_action": "",
            },
        )
        self.client.force_login(self.player_user)
        response = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Préparation des médias")
        self.assertNotContains(response, "SportsBase")

    def test_removing_agent_link_never_deletes_or_changes_player(self):
        self.client.force_login(self.admin)
        snapshot = (self.player.name, self.player.club, self.player.email)
        response = self.client.post(
            reverse(
                "portal:organization_player_remove",
                args=(self.organization.pk, self.first_link.pk),
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Player.objects.filter(pk=self.player.pk).exists())
        self.player.refresh_from_db()
        self.first_link.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            snapshot,
        )
        self.assertFalse(self.first_link.is_active)
        self.assertIsNotNone(self.first_link.ended_at)

    def test_agent_request_creates_no_player(self):
        self.client.force_login(self.agent)
        count_before = Player.objects.count()
        response = self.client.post(
            reverse("portal:agent_player_request"),
            {
                "organization": self.organization.pk,
                "full_name": "Requested Footballer",
                "transfermarkt_url": "https://www.transfermarkt.com/test/profil/spieler/123",
                "club": "Future Club",
                "whatsapp_number": "+21620555666",
                "notes": "À vérifier",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Player.objects.count(), count_before)
        self.assertTrue(
            AgentPlayerRequest.objects.filter(full_name="Requested Footballer").exists()
        )

    def test_viewer_membership_cannot_request_a_player(self):
        viewer = self.make_portal_user(
            "agency-viewer",
            PortalProfile.AccountType.AGENT,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=viewer,
            role=OrganizationMembership.Role.VIEWER,
        )
        self.client.force_login(viewer)
        response = self.client.post(
            reverse("portal:agent_player_request"),
            {
                "organization": self.organization.pk,
                "full_name": "Unauthorized Request",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AgentPlayerRequest.objects.filter(full_name="Unauthorized Request").exists()
        )

    def test_account_creation_service_does_not_modify_player(self):
        snapshot = (self.player.name, self.player.club, self.player.email)
        profile = create_portal_account(
            {
                "account_type": PortalProfile.AccountType.PLAYER,
                "display_name": "New Portal Player",
                "email": "new-portal@example.com",
                "whatsapp_number": "+21620999888",
                "preferred_language": "fr",
                "player": self.player,
                "organization": None,
            },
            created_by=self.admin,
        )
        self.assertTrue(
            PlayerAccess.objects.filter(user=profile.user, player=self.player).exists()
        )
        self.player.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            snapshot,
        )

    def test_magic_link_is_reusable_while_account_is_active(self):
        link, raw_token = PortalAccessLink.issue(
            user=self.player_user,
            created_by=self.admin,
            lifetime=timedelta(days=1),
        )
        url = reverse("portal:magic_access", args=(raw_token,))
        first = self.client.get(url)
        self.assertRedirects(first, reverse("portal:dashboard"))
        link.refresh_from_db()
        self.assertIsNotNone(link.used_at)
        self.client.post(reverse("portal:logout"))
        second = self.client.get(url)
        self.assertRedirects(second, reverse("portal:dashboard"))

    def test_same_magic_link_follows_account_activation(self):
        profile = self.player_user.portal_profile
        _link, raw_token = PortalAccessLink.issue(
            user=self.player_user,
            created_by=self.admin,
            lifetime=timedelta(days=1),
        )
        url = reverse("portal:magic_access", args=(raw_token,))

        self.client.force_login(self.admin)
        self.client.post(
            reverse("portal:account_toggle", args=(profile.pk,)),
            {"action": "deactivate"},
        )
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 410)

        self.client.force_login(self.admin)
        self.client.post(
            reverse("portal:account_toggle", args=(profile.pk,)),
            {"action": "activate"},
        )
        self.client.logout()
        self.assertRedirects(self.client.get(url), reverse("portal:dashboard"))

    def test_inactive_profile_cannot_use_magic_link(self):
        profile = self.player_user.portal_profile
        profile.is_active = False
        profile.save(update_fields=("is_active",))
        _link, raw_token = PortalAccessLink.issue(
            user=self.player_user,
            created_by=self.admin,
            lifetime=timedelta(days=1),
        )
        response = self.client.get(
            reverse("portal:magic_access", args=(raw_token,))
        )
        self.assertEqual(response.status_code, 410)

    def test_portal_user_is_redirected_away_from_internal_dashboard(self):
        self.client.force_login(self.player_user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_non_superuser_cannot_manage_portal_accounts(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("portal:management"))
        self.assertEqual(response.status_code, 403)

    def test_management_and_organization_pages_render_for_admin(self):
        self.client.force_login(self.admin)
        management = self.client.get(reverse("portal:management"))
        organization = self.client.get(
            reverse("portal:organization_detail", args=(self.organization.pk,))
        )
        self.assertEqual(management.status_code, 200)
        self.assertEqual(organization.status_code, 200)
        self.assertContains(management, self.organization.name)
        self.assertContains(organization, self.player.name)

    def test_admin_creates_player_access_without_editing_player(self):
        self.client.force_login(self.admin)
        snapshot = (
            self.hidden_player.name,
            self.hidden_player.club,
            self.hidden_player.email,
        )
        response = self.client.post(
            reverse("portal:account_create"),
            {
                "account_type": PortalProfile.AccountType.PLAYER,
                "display_name": "Hidden Client",
                "email": "hidden-client@example.com",
                "whatsapp_number": "+21620999111",
                "preferred_language": "fr",
                "player": self.hidden_player.pk,
                "organization": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lien sécurisé prêt")
        profile = PortalProfile.objects.get(user__email="hidden-client@example.com")
        self.assertTrue(
            PlayerAccess.objects.filter(
                user=profile.user,
                player=self.hidden_player,
            ).exists()
        )
        self.hidden_player.refresh_from_db()
        self.assertEqual(
            (
                self.hidden_player.name,
                self.hidden_player.club,
                self.hidden_player.email,
            ),
            snapshot,
        )

    def test_account_creation_uses_persistent_credentials_and_email(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal:account_create"),
            {
                "account_type": PortalProfile.AccountType.PLAYER,
                "display_name": self.hidden_player.name,
                "email": self.hidden_player.email,
                "whatsapp_number": "+21620999111",
                "preferred_language": "fr",
                "player": self.hidden_player.pk,
                "organization": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        profile = PortalProfile.objects.get(user__email=self.hidden_player.email)
        temporary_password = response.context["temporary_password"]
        self.assertTrue(profile.user.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/portal/access/", mail.outbox[0].body)
        self.assertIn("réutilisable", mail.outbox[0].body)
        self.assertIn(reverse("portal:login"), mail.outbox[0].body)
        self.assertIn(temporary_password, mail.outbox[0].body)
        self.assertContains(response, "Lien sécurisé principal")

        self.client.logout()
        login_response = self.client.post(
            reverse("portal:login"),
            {
                "username": self.hidden_player.email,
                "password": temporary_password,
            },
        )
        self.assertRedirects(login_response, reverse("portal:dashboard"))

    def test_admin_can_deactivate_and_reactivate_portal_account(self):
        profile = self.player_user.portal_profile
        profile.user.set_password("Player-password-123")
        profile.user.save(update_fields=("password",))
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("portal:account_toggle", args=(profile.pk,)),
            {"action": "deactivate"},
        )
        self.assertRedirects(response, reverse("portal:management"))
        profile.refresh_from_db()
        profile.user.refresh_from_db()
        self.assertFalse(profile.is_active)
        self.assertFalse(profile.user.is_active)

        self.client.logout()
        blocked_login = self.client.post(
            reverse("portal:login"),
            {
                "username": profile.user.email,
                "password": "Player-password-123",
            },
        )
        self.assertEqual(blocked_login.status_code, 200)

        self.client.force_login(self.admin)
        self.client.post(
            reverse("portal:account_toggle", args=(profile.pk,)),
            {"action": "activate"},
        )
        profile.refresh_from_db()
        profile.user.refresh_from_db()
        self.assertTrue(profile.is_active)
        self.assertTrue(profile.user.is_active)

    def test_admin_can_renew_reusable_link_and_prepare_whatsapp(self):
        profile = self.player_user.portal_profile
        legacy_link, legacy_raw_token = PortalAccessLink.issue(
            user=profile.user,
            created_by=self.admin,
            lifetime=timedelta(days=1),
        )
        self.client.get(reverse("portal:magic_access", args=(legacy_raw_token,)))
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal:account_credentials", args=(profile.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["temporary_password"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, "Envoyer le lien sécurisé")
        self.assertContains(response, "peut être ouvert plusieurs fois")
        legacy_link.refresh_from_db()
        self.assertIsNotNone(legacy_link.revoked_at)
        self.client.logout()
        self.assertEqual(
            self.client.get(
                reverse("portal:magic_access", args=(legacy_raw_token,))
            ).status_code,
            410,
        )

    def test_portal_login_accepts_a_fresh_https_csrf_token(self):
        self.player_user.set_password("Player-password-123")
        self.player_user.save(update_fields=("password",))
        csrf_client = Client(enforce_csrf_checks=True)
        login_url = reverse("portal:login")

        page = csrf_client.get(login_url, secure=True)
        csrf_token = csrf_client.cookies["csrftoken"].value
        response = csrf_client.post(
            login_url,
            {
                "username": self.player_user.email,
                "password": "Player-password-123",
                "csrfmiddlewaretoken": csrf_token,
            },
            secure=True,
            HTTP_ORIGIN="https://testserver",
            HTTP_REFERER=f"https://testserver{login_url}",
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'action="{login_url}"')
        self.assertRedirects(response, reverse("portal:dashboard"))

    def test_portal_session_can_switch_to_staff_login_in_same_browser(self):
        self.client.force_login(self.player_user)
        login_page = self.client.get(reverse("user_login"))
        self.assertEqual(login_page.status_code, 200)
        self.assertContains(login_page, "Connexion")

        staff_login = self.client.post(
            reverse("user_login"),
            {
                "username": self.admin.username,
                "password": "test-password",
            },
        )
        self.assertRedirects(staff_login, reverse("dashboard"))

    def test_agent_account_can_link_several_existing_players_without_editing_them(self):
        agency = Organization.objects.create(
            name="Next Career",
            kind=Organization.Kind.AGENT,
            contact_name="Nadia Agent",
            email="nadia@example.com",
            whatsapp_number="+21620777888",
            created_by=self.admin,
        )
        snapshots = {
            player.pk: (player.name, player.club, player.email)
            for player in (self.player, self.hidden_player)
        }
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("portal:account_create"),
            {
                "account_type": PortalProfile.AccountType.AGENT,
                "display_name": "Nadia Agent",
                "email": "nadia@example.com",
                "whatsapp_number": "+21620777888",
                "preferred_language": "fr",
                # Simule un ancien choix joueur encore présent après changement
                # de type dans le navigateur : il doit être ignoré.
                "player": self.second_player.pk,
                "organization": agency.pk,
                "players": [self.player.pk, self.hidden_player.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        profile = PortalProfile.objects.get(user__email="nadia@example.com")
        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=profile.user,
                organization=agency,
                is_active=True,
            ).exists()
        )
        self.assertFalse(PlayerAccess.objects.filter(user=profile.user).exists())
        self.assertSetEqual(
            set(
                OrganizationPlayer.objects.filter(
                    organization=agency,
                    is_active=True,
                ).values_list("player_id", flat=True)
            ),
            {self.player.pk, self.hidden_player.pk},
        )
        for player in (self.player, self.hidden_player):
            player.refresh_from_db()
            self.assertEqual(
                (player.name, player.club, player.email),
                snapshots[player.pk],
            )

    def test_password_change_keeps_portal_session_active(self):
        _link, raw_token = PortalAccessLink.issue(
            user=self.player_user,
            created_by=self.admin,
            lifetime=timedelta(days=1),
        )
        self.player_user.set_password("Old-password-123")
        self.player_user.save(update_fields=("password",))
        self.client.force_login(self.player_user)
        response = self.client.post(
            reverse("portal:password_change"),
            {
                "old_password": "Old-password-123",
                "new_password1": "New-password-456!",
                "new_password2": "New-password-456!",
            },
        )
        self.assertRedirects(response, reverse("portal:dashboard"))
        self.player_user.refresh_from_db()
        self.assertTrue(self.player_user.check_password("New-password-456!"))
        self.assertEqual(
            self.client.get(reverse("portal:dashboard")).status_code,
            200,
        )
        self.client.post(reverse("portal:logout"))
        self.assertRedirects(
            self.client.get(reverse("portal:magic_access", args=(raw_token,))),
            reverse("portal:dashboard"),
        )


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class PortalCollaborationTests(PortalFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.portal_user = self.make_portal_user("collaboration-player")
        PlayerAccess.objects.create(
            user=self.portal_user,
            player=self.player,
            granted_by=self.admin,
        )
        self.version = VideoVersion.objects.create(
            video=self.video,
            version_number=1,
            title="Version client",
            preview_url="https://example.com/video-preview",
            uploaded_by=self.admin,
        )

    def test_client_can_submit_media_for_accessible_video(self):
        self.client.force_login(self.portal_user)
        response = self.client.post(
            reverse("portal:media_submit", args=(self.video.pk,)),
            {
                "category": MediaSubmission.Category.MATCH,
                "title": "Match complet",
                "source_url": "https://example.com/match",
                "notes": "Mon meilleur match",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MediaSubmission.objects.filter(video=self.video).exists())
        self.player.refresh_from_db()
        self.assertEqual(self.player.name, "Alpha Player")

    def test_dashboard_highlights_required_actions_and_order_finances(self):
        self.client.force_login(self.portal_user)

        response = self.client.get(reverse("portal:dashboard"))

        self.assertContains(response, "Actions requises")
        self.assertContains(response, "1 version à valider")
        self.assertContains(response, "Montant total")
        self.assertContains(response, "Déjà payé")
        self.assertContains(response, "Solde")
        self.assertContains(response, "Joueurs suivis")
        self.assertContains(response, "commande active")

    def test_client_cannot_submit_media_for_hidden_video(self):
        self.client.force_login(self.portal_user)
        response = self.client.post(
            reverse("portal:media_submit", args=(self.hidden_video.pk,)),
            {
                "category": MediaSubmission.Category.MATCH,
                "title": "Unauthorized",
                "source_url": "https://example.com/private",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(MediaSubmission.objects.filter(title="Unauthorized").exists())

    def test_read_only_access_cannot_submit_or_approve(self):
        viewer = self.make_portal_user("collaboration-viewer")
        PlayerAccess.objects.create(
            user=viewer,
            player=self.player,
            role=PlayerAccess.Role.VIEWER,
            granted_by=self.admin,
        )
        self.client.force_login(viewer)
        detail = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Transmettre à l’équipe")

        media_response = self.client.post(
            reverse("portal:media_submit", args=(self.video.pk,)),
            {
                "category": MediaSubmission.Category.MATCH,
                "title": "Viewer upload",
                "source_url": "https://example.com/viewer-upload",
            },
        )
        approval_response = self.client.post(
            reverse("portal:version_approve", args=(self.version.pk,))
        )
        self.assertEqual(media_response.status_code, 404)
        self.assertEqual(approval_response.status_code, 404)
        self.assertFalse(MediaSubmission.objects.filter(title="Viewer upload").exists())
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, VideoVersion.Status.PENDING)

    def test_final_delivery_link_is_hidden_until_fully_paid(self):
        self.video.status = Video.StatusChoices.DELIVERED
        self.video.video_link = "https://example.com/final-private-video"
        self.video.save(update_fields=("status", "video_link"))
        self.client.force_login(self.portal_user)

        unpaid = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertNotContains(unpaid, self.video.video_link)

        self.invoice.amount_paid = self.invoice.total_amount
        self.invoice.status = "paid"
        self.invoice.save(update_fields=("amount_paid", "status"))
        paid = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertContains(paid, self.video.video_link)

    def test_hidden_video_is_absent_from_portal_without_changing_its_player(self):
        player_snapshot = (self.player.name, self.player.club, self.player.email)
        self.video.client_portal_visible = False
        self.video.save(update_fields=("client_portal_visible",))
        self.client.force_login(self.portal_user)

        dashboard = self.client.get(reverse("portal:dashboard"))
        detail = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertNotContains(dashboard, self.video.season)
        self.assertEqual(detail.status_code, 404)
        self.player.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            player_snapshot,
        )

    def test_paid_youtube_delivery_is_embedded_in_video_history(self):
        self.video.status = Video.StatusChoices.DELIVERED
        self.video.video_link = "https://www.youtube.com/watch?v=abcdefghijk"
        self.video.save(update_fields=("status", "video_link"))
        self.invoice.amount_paid = self.invoice.total_amount
        self.invoice.status = "paid"
        self.invoice.save(update_fields=("amount_paid", "status"))
        self.client.force_login(self.portal_user)

        dashboard = self.client.get(reverse("portal:dashboard"))
        player_page = self.client.get(
            reverse("portal:player", args=(self.player.pk,))
        )
        video_page = self.client.get(
            reverse("portal:video", args=(self.video.pk,))
        )
        expected_embed = "https://www.youtube-nocookie.com/embed/abcdefghijk"
        self.assertContains(dashboard, expected_embed)
        self.assertContains(player_page, expected_embed)
        self.assertContains(video_page, expected_embed)
        self.assertContains(video_page, "Ouvrir sur YouTube")
        self.assertContains(video_page, "Vidéo livrée")
        self.assertContains(dashboard, "Historique des vidéos")

    def test_video_timeline_combines_saved_statuses_payments_and_updates(self):
        self.video.status = Video.StatusChoices.IN_PROGRESS
        self.video.save(update_fields=("status",))
        Payment.objects.create(
            player=self.player,
            video=self.video,
            amount=Decimal("150"),
            payment_type="partial",
            payment_method="bank_transfer",
            remaining_balance=Decimal("250"),
            invoice=self.invoice,
            created_by=self.admin,
        )
        VideoActivity.objects.create(
            video=self.video,
            kind=VideoActivity.Kind.VERSION,
            visibility=VideoActivity.Visibility.CLIENT,
            message="Une nouvelle prévisualisation est disponible.",
            created_by=self.admin,
        )
        counts_before = (
            self.video.status_history.count(),
            self.video.payments.count(),
            self.video.portal_activities.count(),
        )
        self.client.force_login(self.portal_user)

        response = self.client.get(reverse("portal:video", args=(self.video.pk,)))

        self.assertContains(response, "Production démarrée")
        self.assertContains(response, "Paiement partiel enregistré")
        self.assertContains(response, "150.00")
        self.assertContains(response, "virement bancaire")
        self.assertContains(response, "Une nouvelle prévisualisation est disponible.")
        self.assertContains(response, "portal-finance-card", count=3)
        self.assertEqual(
            (
                self.video.status_history.count(),
                self.video.payments.count(),
                self.video.portal_activities.count(),
            ),
            counts_before,
        )

    def test_completed_collab_has_a_clear_client_facing_explanation(self):
        self.video.status = Video.StatusChoices.COMPLETED_COLLAB
        self.video.save(update_fields=("status",))
        self.client.force_login(self.portal_user)

        response = self.client.get(reverse("portal:video", args=(self.video.pk,)))

        self.assertContains(
            response,
            "En cours de finition et classification des séquences",
        )
        self.assertContains(
            response,
            "Notre équipe finalise le montage et classe les séquences sélectionnées.",
        )

    def test_timecoded_revision_creates_overlay_only(self):
        self.client.force_login(self.portal_user)
        response = self.client.post(
            reverse("portal:revision_request", args=(self.version.pk,)),
            {"timecode": "02:35", "comment": "Changer cette action."},
        )
        self.assertEqual(response.status_code, 302)
        revision = RevisionRequest.objects.get(version=self.version)
        self.assertEqual(revision.timecode_seconds, 155)
        self.assertEqual(
            VideoWorkflow.objects.get(video=self.video).stage,
            VideoWorkflow.Stage.REVISIONS,
        )
        self.video.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)

    def test_approval_moves_portal_workflow_to_awaiting_balance(self):
        self.client.force_login(self.portal_user)
        response = self.client.post(
            reverse("portal:version_approve", args=(self.version.pk,))
        )
        self.assertEqual(response.status_code, 302)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, VideoVersion.Status.APPROVED)
        self.assertEqual(
            VideoWorkflow.objects.get(video=self.video).stage,
            VideoWorkflow.Stage.AWAITING_BALANCE,
        )
        self.video.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(self.video.status, Video.StatusChoices.PENDING)
        self.assertEqual(self.invoice.amount_paid, Decimal("100"))

    def test_payment_link_is_visible_only_to_authorized_player(self):
        payment_request = PaymentRequest.objects.create(
            video=self.video,
            label="Solde",
            amount=Decimal("400"),
            payment_url="https://payments.example.com/ms-football/123",
            created_by=self.admin,
        )
        self.client.force_login(self.portal_user)
        response = self.client.post(
            reverse("portal:payment_open", args=(payment_request.pk,))
        )
        self.assertRedirects(
            response,
            payment_request.payment_url,
            fetch_redirect_response=False,
        )
        payment_request.refresh_from_db()
        self.assertEqual(payment_request.status, PaymentRequest.Status.OPENED)

    def test_manifest_and_service_worker_are_public_but_contain_no_data(self):
        manifest = self.client.get(reverse("portal:manifest"))
        worker = self.client.get(reverse("portal:service_worker"))
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["display"], "standalone")
        self.assertEqual(worker.status_code, 200)
        self.assertNotContains(worker, self.player.name)

    def test_portal_pages_disable_browser_caching(self):
        self.client.force_login(self.portal_user)
        response = self.client.get(reverse("portal:video", args=(self.video.pk,)))
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(
            response["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )
