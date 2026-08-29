from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sportsbase_data", "0004_match_analysis_payload"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsbasesubscription",
            name="currency",
            field=models.CharField(
                choices=[("TND", "TND"), ("EUR", "EUR"), ("USD", "USD")],
                default="TND",
                max_length=3,
                verbose_name="Devise",
            ),
        ),
        migrations.AddField(
            model_name="sportsbasesubscription",
            name="payment_url",
            field=models.URLField(
                blank=True,
                help_text="Facultatif : lien sécurisé affiché dans l’espace joueur pour régler l’abonnement.",
                verbose_name="Lien de paiement",
            ),
        ),
        migrations.AddField(
            model_name="sportsbasesubscription",
            name="total_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                verbose_name="Prix de l’abonnement",
            ),
        ),
        migrations.CreateModel(
            name="PerformanceSubscriptionPayment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="Montant",
                    ),
                ),
                (
                    "payment_date",
                    models.DateField(
                        default=django.utils.timezone.localdate,
                        verbose_name="Date du paiement",
                    ),
                ),
                (
                    "payment_method",
                    models.CharField(
                        choices=[
                            ("cash", "Espèces"),
                            ("bank_transfer", "Virement bancaire"),
                            ("la_poste", "La Poste"),
                            ("online", "Paiement en ligne"),
                            ("other", "Autre"),
                        ],
                        default="bank_transfer",
                        max_length=24,
                        verbose_name="Mode de paiement",
                    ),
                ),
                ("reference", models.CharField(blank=True, max_length=120, verbose_name="Référence")),
                ("notes", models.TextField(blank=True, verbose_name="Notes")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_performance_subscription_payments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payments",
                        to="sportsbase_data.sportsbasesubscription",
                        verbose_name="Abonnement Performance",
                    ),
                ),
            ],
            options={
                "verbose_name": "Paiement d’abonnement Performance",
                "verbose_name_plural": "Paiements d’abonnements Performance",
                "ordering": ("-payment_date", "-created_at"),
            },
        ),
    ]
