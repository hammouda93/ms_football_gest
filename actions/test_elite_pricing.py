"""Fictional regression data only; no native credentials or production writes."""
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import transaction
from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.utils import timezone

from client_portal.models import Organization, OrganizationPlayer
from gestion_joueurs.forms import VideoForm
from gestion_joueurs.models import Invoice, Payment, Player, Video, VideoEditor
from gestion_joueurs.utils import actor_context
from gestion_joueurs.views import create_video_highlight, edit_video
from .engine import Engine
from .effects import effects_context
from .registry import SIMPLE
from .view_adapter import request_for
from . import readback


@override_settings(ELITE_ATHLETES_ORGANIZATION_ID=2)
class ElitePricingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="elite-test", email="elite@example.invalid", password="test-only"
        )
        self.editor = VideoEditor.objects.create(user=self.admin)
        self.other_editor = VideoEditor.objects.create(
            user=User.objects.create_user(username="elite-test-editor", password="test-only")
        )
        self.elite = Organization.objects.create(pk=2, name="Renamed fictional agency", kind="agent")
        self.other = Organization.objects.create(pk=3, name="Sami Agence Elites", kind="academy")
        self.today = timezone.localdate()
        self.engine = Engine(self.admin.pk)

    def player(self, name, org=None, pack=None):
        player = Player.objects.create(name=name, club="Fiction FC", league="OC", position="DF")
        if org:
            OrganizationPlayer.objects.create(
                player=player, organization=org, expected_matches=pack, added_by=self.admin
            )
        return player

    def order(self, player, org, pack):
        return dict(player=player, editor=self.editor.pk, client_organization=org.pk,
                    whatsapp_conversation_date=self.today.isoformat(), deadline_from_whatsapp=True,
                    match_package=pack, season="2026/2027", advance_payment="0.00", info="fiction")

    def web_data(self, player, org=None, pack=None, price="999.00"):
        data = dict(player=player.pk, create_video="1", status="pending", editor=self.editor.pk,
                    total_payment=price, advance_payment="0.00", matches_processed=0,
                    season="2026/2027", seasons_to_process=1,
                    deadline=(self.today + timedelta(days=5)).isoformat(), info="fiction")
        if org:
            data.update(client_organization=org.pk, match_package=pack,
                        whatsapp_conversation_date=self.today.isoformat(), deadline_from_whatsapp="on")
        return data

    def assert_amounts(self, video, price):
        video.refresh_from_db()
        invoice = Invoice.objects.get(video=video)
        self.assertEqual(video.total_payment, Decimal(price))
        self.assertEqual(invoice.total_amount, Decimal(price))
        self.assertEqual(invoice.amount_paid, Decimal("0"))
        self.assertFalse(Payment.objects.filter(video=video).exists())

    def apply_verified(self, steps):
        # SQLite cannot execute the production PostgreSQL advisory-lock/consent
        # envelope. Use the actual validation, snapshots, application transaction,
        # effects and exact graph comparison on the disposable default database.
        self.engine.validate(steps)
        snapshots = self.engine.snapshots(steps)
        plan = SimpleNamespace(actor_id=self.admin.pk, steps=steps, snapshots=snapshots,
                               results={}, effects={})
        real_rows = readback.rows

        def test_rows(label, _alias="default", **filters):
            return real_rows(label, _alias="default", **filters)

        with transaction.atomic(), actor_context(self.admin), effects_context() as effects:
            baseline = readback.graph(plan, {}, _alias="default")
            plan.results = self.engine._apply(steps, self.admin)
            plan.effects = effects
            after = readback.graph(plan, plan.results, _alias="default")
            with patch.object(readback, "ALIAS", "default"), patch.object(readback, "rows", test_rows):
                self.assertEqual(after, readback.expected_graph(plan, baseline, after))
        return plan

    def test_three_packs_web_and_hermes_and_generic(self):
        for org, prices in ((self.elite, {3: "350", 5: "500", 10: "700"}),
                            (self.other, {3: "300", 5: "350", 10: "400"})):
            for pack, price in prices.items():
                with self.subTest(org=org.pk, pack=pack):
                    web = self.player(f"web {org.pk} {pack}", org, pack)
                    data = self.web_data(web, org, pack)
                    form = VideoForm(data, user=self.admin, player=web)
                    self.assertTrue(form.is_valid(), form.errors)
                    tariff = json.loads(form.fields["match_package"].widget.attrs["data-package-tariffs"])
                    displayed = tariff.get(str(org.pk), tariff["default"])[str(pack)]
                    self.assertEqual(Decimal(displayed), Decimal(price))
                    self.assertIn(f"{pack} matchs = {price} DT", form.fields["match_package"].help_text)
                    self.assertEqual(form.cleaned_data["total_payment"], Decimal(price))
                    with actor_context(self.admin):
                        response = create_video_highlight(request_for(self.admin.pk, data))
                    self.assertEqual(response.status_code, 302)
                    self.assert_amounts(Video.objects.get(player=web), price)

                    existing = self.player(f"bridge {org.pk} {pack}", org, pack)
                    step = dict(op="video.order", **{"as": "order"}, values=self.order(existing.pk, org, pack))
                    count = Player.objects.count()
                    plan = self.apply_verified([step])
                    self.assertEqual(plan.snapshots["__preview__"]["orders"][0]["price"], f"{price}.00")
                    self.assertEqual(Player.objects.count(), count)
                    video = Video.objects.get(pk=plan.results["order"])
                    self.assertEqual(video.player_id, existing.pk)
                    self.assertEqual(video.deadline, self.today + timedelta(days=5))
                    self.assert_amounts(video, price)
                    with self.assertRaisesRegex(ValueError, "duplicate_order"):
                        with transaction.atomic():
                            self.engine._apply([step], self.admin)

    def test_direct_and_explicit_conditions(self):
        direct = self.player("direct")
        data = self.web_data(direct, price="432.10")
        with actor_context(self.admin):
            self.assertEqual(create_video_highlight(request_for(self.admin.pk, data)).status_code, 302)
        self.assert_amounts(Video.objects.get(player=direct), "432.10")
        adapter = SIMPLE["video.conditions.create"]
        for pack, price in ((3, "350.00"), (5, "500.00"), (10, "700.00")):
            player = self.player(f"explicit {pack}", self.elite, pack)
            values = self.order(player.pk, self.elite, pack)
            values.update(total_payment=price, deadline=(self.today + timedelta(days=5)).isoformat())
            with self.assertRaisesRegex(ValueError, "package_price_mismatch"):
                adapter.cleaned(dict(values, total_payment="1.00"), self.admin.pk)
            with actor_context(self.admin):
                video = adapter.apply(values, self.admin.pk)
            self.assert_amounts(video, price)
        direct2 = self.player("direct conditions")
        values = dict(player=direct2.pk, editor=self.editor.pk, total_payment="477.25",
                      advance_payment="0.00", season="2026/2027", deadline_from_whatsapp=False,
                      whatsapp_conversation_date=self.today.isoformat(),
                      deadline=(self.today + timedelta(days=5)).isoformat())
        with actor_context(self.admin):
            self.assert_amounts(adapter.apply(values, self.admin.pk), "477.25")

    def test_historical_web_and_conditions_amend_keep_invoice_and_payments(self):
        player = self.player("historical", self.elite, 5)
        with actor_context(self.admin):
            video = Video.objects.create(player=player, editor=self.editor, client_organization=self.elite,
                match_package=5, advance_payment=Decimal("100.00"), total_payment=Decimal("350.00"),
                deadline=self.today + timedelta(days=5), season="2026/2027")
        invoice = Invoice.objects.create(video=video, total_amount=Decimal("350.00"),
                   amount_paid=Decimal("100.00"), status="partially_paid", created_by=self.admin)
        Payment.objects.create(player=player, video=video, invoice=invoice, amount=Decimal("100.00"),
            payment_type="advance", payment_method="cash", remaining_balance=Decimal("250.00"), created_by=self.admin)
        before = list(Payment.objects.filter(video=video).values())
        financial = Invoice.objects.filter(pk=invoice.pk).values().get()
        form = VideoForm(instance=video, user=self.admin)
        self.assertEqual(form["total_payment"].value(), Decimal("350.00"))
        self.assertEqual(form.fields["match_package"].widget.attrs["data-existing-order"], "true")
        data = {k:v for k,v in model_to_dict(video).items() if k in VideoForm._meta.fields and v is not None}
        for field in ("client_portal_visible", "deadline_from_whatsapp"):
            if not data.get(field):
                data.pop(field, None)
        data.update(deadline=(self.today + timedelta(days=8)).isoformat(), info="updated note")
        with actor_context(self.admin):
            self.assertEqual(edit_video(request_for(self.admin.pk, data), video.pk).status_code, 302)
        adapter = SIMPLE["video.conditions.amend"]
        vals = dict(id=video.pk, editor=self.other_editor.pk)
        preview = adapter.preview(dict(op="video.conditions.amend", **{"as":"amend"}, values=vals), self.admin.pk)
        self.assertEqual(preview["financial"]["old"], preview["financial"]["new"])
        with actor_context(self.admin):
            adapter.apply(vals, self.admin.pk)
        video.refresh_from_db()
        self.assertEqual(video.editor_id, self.other_editor.pk)
        self.assertEqual(video.deadline, self.today + timedelta(days=8))
        self.assertEqual(video.total_payment, Decimal("350.00"))
        self.assertEqual(Invoice.objects.filter(pk=invoice.pk).values().get(), financial)
        self.assertEqual(list(Payment.objects.filter(video=video).values()), before)
        with self.assertRaises(ValueError):
            adapter.cleaned(dict(id=video.pk, match_package=10), self.admin.pk)
        with self.assertRaises(ValueError):
            adapter.cleaned(dict(id=video.pk, total_payment="400.00"), self.admin.pk)
        with actor_context(self.admin):
            adapter.apply(dict(id=video.pk, total_payment="500.00"), self.admin.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal("500.00"))
        self.assertEqual(list(Payment.objects.filter(video=video).values()), before)

    def composed(self, name, link_pack=5, order_pack=5):
        return [
            dict(op="player.profile.create", **{"as":"player"}, values=dict(name=name,
                 date_of_birth="2005-01-02", club="Fiction FC", league="OC", position="DF")),
            dict(op="organization.link", **{"as":"link"}, values=dict(player={"ref":"player"},
                 organization=self.elite.pk, expected_matches=link_pack)),
            dict(op="video.order", **{"as":"order"}, values=self.order({"ref":"player"}, self.elite, order_pack)),
        ]

    def test_composed_new_player_and_rollback_and_duplicate(self):
        steps = self.composed("fiction new")
        plan = self.apply_verified(steps)
        self.assert_amounts(Video.objects.get(pk=plan.results["order"]), "500")
        self.assertEqual(OrganizationPlayer.objects.get(pk=plan.results["link"]).expected_matches, 5)
        counts = tuple(m.objects.count() for m in (Player, OrganizationPlayer, Video, Invoice, Payment))
        for bad, error in ((self.composed("fiction failed", 3, 5), "organization_link_mismatch"),
                           (steps, "duplicate_record")):
            self.engine.validate(bad)
            with self.assertRaisesRegex(ValueError, error):
                with transaction.atomic(), actor_context(self.admin):
                    self.engine._apply(bad, self.admin)
            self.assertEqual(tuple(m.objects.count() for m in (Player, OrganizationPlayer, Video, Invoice, Payment)), counts)

    def test_order_contract_constraints(self):
        player = self.player("constraints", self.elite, 3)
        values = self.order(player.pk, self.elite, 5)
        step = dict(op="video.order", **{"as":"order"}, values=values)
        with self.assertRaisesRegex(ValueError, "organization_link_mismatch"):
            with transaction.atomic():
                self.engine._apply([step], self.admin)
        for override, error in ((dict(advance_payment="1.00"), "payment_not_supported"),
                                (dict(deadline_from_whatsapp=False), "automatic_deadline_required")):
            with self.assertRaisesRegex(ValueError, error):
                self.engine.validate([dict(step, values=dict(values, **override))])
        self.assertFalse(Video.objects.filter(player=player).exists())
