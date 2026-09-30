import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from gestion_joueurs.models import Player
from .models import AgentAction


class AgentApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser("agent-test", "test@example.invalid", "test-only")
        self.client.force_login(self.owner)
        self.player = Player.objects.create(name="Test Player", club="Original FC", league="L1", position="DF", email="player@example.invalid")

    def post(self, name, value):
        return self.client.post(reverse(f"agent:{name}"), json.dumps(value), content_type="application/json")

    def test_catalog_requires_active_superadministrator(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("agent:catalog")).status_code, 401)
        staff = User.objects.create_user("staff", password="test-only", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("agent:catalog")).status_code, 403)

    def test_complete_catalog_and_safe_schema(self):
        catalog = self.client.get(reverse("agent:catalog")).json()
        labels = {item["entity"] for item in catalog["database"]}
        self.assertIn("gestion_joueurs.payment", labels)
        self.assertIn("sportsbase_data.performancereport", labels)
        self.assertIn("client_portal.organization", labels)
        self.assertIn("prospects.prospect", labels)
        self.assertGreater(len(catalog["actions"]), 30)
        schema = self.client.get(reverse("agent:describe"), {"entity": "auth.user"}).json()
        self.assertNotIn("password", {item["name"] for item in schema["fields"]})

    def test_all_catalog_entities_and_action_routes_are_resolvable(self):
        from . import actions, data
        for item in data.catalog():
            with self.subTest(entity=item["entity"]):
                self.assertGreater(len(data.describe(item["entity"])["fields"]), 0)
                self.assertEqual(self.post("query", {"entity": item["entity"], "limit": 1}).status_code, 200)
        for item in actions.catalog():
            with self.subTest(action=item["action"]):
                parameters = {key: "intro" if key == "pipeline" else 1 for key in item["parameters"]}
                spec, path = actions.validate(item["action"], parameters)
                self.assertTrue(path.startswith("/"))
                if spec.entity:
                    data.get_model(spec.entity)

    def test_queries_are_paginated_and_aggregate_actual_database_rows(self):
        Player.objects.create(name="Other", club="Other FC", league="L1", position="FW")
        result = self.post("query", {"entity": "gestion_joueurs.player", "fields": ["id", "name", "club"], "limit": 1}).json()
        self.assertEqual(result["total"], 2)
        self.assertTrue(result["hasMore"])
        grouped = self.post("query", {"entity": "gestion_joueurs.player", "groupBy": ["league"], "aggregates": [{"function": "count", "field": "id", "alias": "players"}]}).json()
        self.assertEqual(grouped["rows"], [{"league": "L1", "players": 2}])

    def test_credentials_raw_sql_unbounded_queries_and_hidden_relations_are_rejected(self):
        for query in [
            {"entity": "auth.user", "fields": ["password"]},
            {"entity": "django_session.session"},
            {"entity": "gestion_joueurs.player", "sql": "DELETE FROM players"},
            {"entity": "gestion_joueurs.player", "limit": 10001},
            {"entity": "gestion_joueurs.video", "fields": ["editor__user__password"]},
            {"entity": "gestion_joueurs.player", "filters": {"id__in": "not-a-list"}},
        ]:
            self.assertEqual(self.post("query", query).status_code, 400)

    def proposal(self, club="New FC"):
        response = self.post("action_prepare", {"action": "edit_player", "parameters": {"player_id": self.player.pk}, "changes": {"club": club}})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_prepare_is_reviewable_and_does_not_change_business_data(self):
        plan = self.proposal()
        self.player.refresh_from_db()
        self.assertEqual(self.player.club, "Original FC")
        self.assertEqual(plan["changes"][0]["before"], "Original FC")
        self.assertEqual(plan["changes"][0]["after"], "New FC")
        self.assertEqual(plan["status"], "requires_confirmation")

    def test_confirm_uses_the_existing_view_preserves_other_fields_and_deduplicates(self):
        plan = self.proposal()
        payload = {"planId": plan["planId"], "confirmation": True}
        result = self.post("action_confirm", payload)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["status"], "success", result.content)
        self.player.refresh_from_db()
        self.assertEqual(self.player.club, "New FC")
        self.assertEqual(self.player.name, "Test Player")
        self.assertEqual(self.player.email, "player@example.invalid")
        self.assertEqual(self.post("action_confirm", payload).json(), result.json())

    def test_modified_expired_and_cancelled_proposals_do_not_write(self):
        plan = self.proposal()
        Player.objects.filter(pk=self.player.pk).update(club="Changed by someone else")
        result = self.post("action_confirm", {"planId": plan["planId"], "confirmation": True}).json()
        self.assertEqual(result["status"], "failed")
        self.player.refresh_from_db()
        self.assertEqual(self.player.club, "Changed by someone else")
        expired = self.proposal()
        AgentAction.objects.filter(pk=expired["planId"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post("action_confirm", {"planId": expired["planId"], "confirmation": True}).status_code, 400)
        cancelled = self.proposal()
        result = self.post("action_confirm", {"planId": cancelled["planId"], "cancel": True}).json()
        self.assertEqual(result["status"], "cancelled")

    def test_invalid_form_values_and_cross_account_confirmation_cannot_write(self):
        self.assertEqual(self.post("action_prepare", {"action": "edit_player", "parameters": {"player_id": self.player.pk}, "changes": {"league": "INVALID"}}).status_code, 400)
        plan = self.proposal()
        other = User.objects.create_superuser("other-admin", "other@example.invalid", "test-only")
        self.client.force_login(other)
        self.assertEqual(self.post("action_confirm", {"planId": plan["planId"], "confirmation": True}).status_code, 404)

    def test_csrf_is_enforced_on_queries_and_confirmations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("agent:query"), json.dumps({"entity": "gestion_joueurs.player"}), content_type="application/json").status_code, 403)

    def test_payment_executes_existing_bookkeeping_once(self):
        from decimal import Decimal
        from gestion_joueurs.models import Video, VideoEditor, Invoice, Payment
        from gestion_joueurs.utils import set_current_user
        set_current_user(self.owner)
        editor = VideoEditor.objects.create(user=self.owner)
        video = Video.objects.create(player=self.player, editor=editor, total_payment=100, advance_payment=0, season="2025/2026", deadline=timezone.localdate() + timedelta(days=7))
        Invoice.objects.create(video=video, total_amount=100, amount_paid=0, created_by=self.owner)
        proposal = self.post("action_prepare", {"action": "record_payment", "parameters": {"video_id": video.pk}, "changes": {"amount": "25.00", "payment_method": "cash", "payment_type": "advance"}})
        self.assertEqual(proposal.status_code, 200, proposal.content)
        payload = {"planId": proposal.json()["planId"], "confirmation": True}
        result = self.post("action_confirm", payload)
        self.assertEqual(result.json()["status"], "success", result.content)
        self.assertEqual(self.post("action_confirm", payload).json(), result.json())
        self.assertEqual(Payment.objects.filter(video=video).count(), 1)
        self.assertEqual(Invoice.objects.get(video=video).amount_paid, Decimal("25.00"))
        self.assertEqual(Payment.objects.get(video=video).remaining_balance, Decimal("75.00"))

    def test_post_only_prospect_conversion_can_be_prepared_without_running_it(self):
        from prospects.models import Prospect
        prospect = Prospect.objects.create(full_name="Potential player", whatsapp_number="21612345678")
        proposal = self.post("action_prepare", {"action": "prospects:prospect_convert", "parameters": {"pk": prospect.pk}, "changes": {}})
        self.assertEqual(proposal.status_code, 200, proposal.content)
        self.assertEqual(Player.objects.count(), 1)

    def test_invalid_site_response_rolls_back_even_if_a_view_changed_data(self):
        plan = self.proposal()
        from django.http import HttpResponse
        from .actions import dispatch
        def rejected(request, path, method="GET", values=None):
            if method == "GET":
                return dispatch(request, path, method, values)
            Player.objects.filter(pk=self.player.pk).update(club="Partial write")
            return HttpResponse('<ul class="errorlist"><li>Rejected</li></ul>', status=200), []
        with patch("agent_api.actions.dispatch", side_effect=rejected):
            result = self.post("action_confirm", {"planId": plan["planId"], "confirmation": True}).json()
        self.assertEqual(result["status"], "failed")
        self.player.refresh_from_db()
        self.assertEqual(self.player.club, "Original FC")
