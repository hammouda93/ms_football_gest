"""Hermes Highlight video payment contract — isolated regression tests.

No bank transfer, payment-provider API or production record is touched.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from gestion_joueurs.models import Invoice, Payment, Player, Video, VideoEditor
from gestion_joueurs.utils import actor_context
from .registry import SIMPLE, catalogue
from .readback import graph, expected_graph


class HighlightPaymentContractTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser(
            username="highlight-payment-admin",
            email="highlight-payment-admin@example.invalid",
            password="test-only",
        )
        self.editor_user=get_user_model().objects.create_user(
            username="payment-editor",password="test-only",
        )
        self.editor=VideoEditor.objects.create(user=self.editor_user)
        self.player=Player.objects.create(
            name="Payment Sample Player",club="Example FC",league="OC",
            position="FW",email="payment-player@example.invalid",
        )
        self.video=Video.objects.create(
            player=self.player,editor=self.editor,
            status=Video.StatusChoices.PENDING,
            advance_payment=Decimal("100.00"),
            total_payment=Decimal("350.00"),
            deadline=timezone.localdate()+timedelta(days=7),
            season="2025/2026",club=self.player.club,league=self.player.league,
        )
        self.invoice=Invoice.objects.create(
            video=self.video,total_amount=Decimal("350.00"),
            amount_paid=Decimal("100.00"),status="partially_paid",
            created_by=self.admin,
        )
        self.adapter=SIMPLE["finance.highlight.payment.record"]

    def values(self,amount="150.00",method="bank_transfer"):
        return {"video":self.video.pk,"amount":amount,"payment_method":method}

    def test_existing_contract_accepts_no_payment_type(self):
        from .mount import APPROVED_OPERATIONS
        self.assertEqual(set(catalogue()),APPROVED_OPERATIONS)
        contract=self.adapter.contract()
        self.assertEqual(contract["currency"],"TND")
        self.assertIn("finance.highlight.payment.record",catalogue())
        self.assertEqual(set(contract["required"]),{"video","amount","payment_method"})
        self.assertIn("payment_type",contract["fields"])
        from .engine import Engine
        step={"as":"receipt","op":"finance.highlight.payment.record","values":self.values()}
        Engine(self.admin.pk).validate([step])

    def test_partial_payment_preview_does_not_write(self):
        preview=self.adapter.preview({
            "as":"receipt","op":"finance.highlight.payment.record","values":self.values(),
        },self.admin.pk)
        self.assertEqual(preview["new"]["payment_type"],"partial")
        self.assertEqual(preview["new"]["amount"],"150.00")
        self.assertEqual(preview["financial"]["before"]["remaining_balance"],"250.00")
        self.assertEqual(preview["financial"]["after"]["remaining_balance"],"100.00")
        self.assertEqual(preview["invoice"]["new"]["amount_paid"],"250.00")
        self.assertEqual(preview["invoice"]["new"]["status"],"partially_paid")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid,Decimal("100.00"))
        self.assertFalse(Payment.objects.filter(video=self.video).exists())

    def test_partial_payment_apply_and_readback_match(self):
        vals=self.values("150.00")
        step={"as":"receipt","op":"finance.highlight.payment.record","values":vals}
        preview=self.adapter.preview(step,self.admin.pk)
        fake_plan=SimpleNamespace(
            actor_id=self.admin.pk,steps=[step],
            snapshots={"__preview__":{"changes":[preview]}},
            results={},effects={},
        )
        with transaction.atomic(),actor_context(self.admin):
            before=graph(fake_plan,{},_alias="default")
            record=self.adapter.apply(vals,self.admin.pk)
            fake_plan.results={"receipt":record.pk}
            after=graph(fake_plan,fake_plan.results,_alias="default")
            self.assertEqual(after,expected_graph(fake_plan,before,after))
        record.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(record.amount,Decimal("150.00"))
        self.assertEqual(record.payment_type,"partial")
        self.assertEqual(record.payment_method,"bank_transfer")
        self.assertEqual(record.remaining_balance,Decimal("100.00"))
        self.assertEqual(record.created_by_id,self.admin.pk)
        self.assertEqual(record.video_id,self.video.pk)
        self.assertEqual(self.invoice.amount_paid,Decimal("250.00"))
        self.assertEqual(self.invoice.status,"partially_paid")

    def test_final_payment_closes_invoice(self):
        preview=self.adapter.preview({
            "as":"receipt","op":"finance.highlight.payment.record",
            "values":self.values("250.00","cash"),
        },self.admin.pk)
        self.assertEqual(preview["new"]["payment_type"],"final")
        self.assertEqual(preview["financial"]["after"]["remaining_balance"],"0.00")
        with transaction.atomic(),actor_context(self.admin):
            record=self.adapter.apply(self.values("250.00","cash"),self.admin.pk)
        self.invoice.refresh_from_db()
        self.assertEqual(record.payment_type,"final")
        self.assertEqual(record.remaining_balance,Decimal("0.00"))
        self.assertEqual(self.invoice.amount_paid,self.invoice.total_amount)
        self.assertEqual(self.invoice.status,"paid")

    def test_legacy_payment_type_is_accepted_but_calculated(self):
        values={**self.values("250.00"),"payment_type":"advance"}
        with transaction.atomic(),actor_context(self.admin):
            result=self.adapter.apply(values,self.admin.pk)
        self.assertEqual(result.payment_type,"final")

    def test_zero_negative_oversized_and_invalid_amount_rejected(self):
        for amount in ("0.00","-1.00","250.01","99999999999.00","abc"):
            with self.subTest(amount=amount),self.assertRaises(ValueError):
                self.adapter.cleaned(self.values(amount),self.admin.pk)
        self.assertFalse(Payment.objects.filter(video=self.video).exists())
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid,Decimal("100.00"))

    def test_invalid_method_and_non_superuser_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter.cleaned(self.values(method="cryptocurrency"),self.admin.pk)
        with self.assertRaises(PermissionError):
            self.adapter.cleaned(self.values(),self.editor_user.pk)

    def test_invoice_required(self):
        self.invoice.delete()
        with self.assertRaises(ValueError):
            self.adapter.cleaned(self.values(),self.admin.pk)
        self.assertFalse(Payment.objects.filter(video=self.video).exists())

    def test_stale_payment_plan_snapshot_detects_prior_payment(self):
        vals=self.values("150.00")
        before=self.adapter.snapshot(vals,self.admin.pk)
        with transaction.atomic(),actor_context(self.admin):
            self.adapter.apply(vals,self.admin.pk)
        after=self.adapter.snapshot(vals,self.admin.pk)
        self.assertNotEqual(before,after)
        self.assertEqual(Payment.objects.filter(video=self.video).count(),1)

    def test_reposting_full_remaining_amount_cannot_overpay(self):
        vals=self.values("250.00")
        with transaction.atomic(),actor_context(self.admin):
            self.adapter.apply(vals,self.admin.pk)
        with self.assertRaises(ValueError):
            self.adapter.cleaned(vals,self.admin.pk)
        self.assertEqual(Payment.objects.filter(video=self.video).count(),1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid,Decimal("350.00"))
