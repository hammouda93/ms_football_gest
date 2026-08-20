from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gestion_joueurs.models import Invoice, Player, Video, VideoEditor
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
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
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
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            snapshot,
        )

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

    def test_magic_link_is_single_use(self):
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
        self.assertEqual(second.status_code, 410)

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
        snapshot = (self.player.name, self.player.club, self.player.email)
        response = self.client.post(
            reverse("portal:account_create"),
            {
                "account_type": PortalProfile.AccountType.PLAYER,
                "display_name": "Alpha Client",
                "email": "alpha-client@example.com",
                "whatsapp_number": "+21620999111",
                "preferred_language": "fr",
                "player": self.player.pk,
                "organization": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lien sécurisé créé")
        profile = PortalProfile.objects.get(user__email="alpha-client@example.com")
        self.assertTrue(
            PlayerAccess.objects.filter(user=profile.user, player=self.player).exists()
        )
        self.player.refresh_from_db()
        self.assertEqual(
            (self.player.name, self.player.club, self.player.email),
            snapshot,
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
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
