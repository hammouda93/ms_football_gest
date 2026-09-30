from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("client_portal", "0002_organizationplayer_ended_at"),
        ("gestion_joueurs", "0058_video_intro_presentation_style"),
    ]

    operations = [
        migrations.AddField(
            model_name="video",
            name="client_organization",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Organisation cliente à l’origine de cette commande. "
                    "La relation reste enregistrée sur la vidéo même si le joueur change d’agence plus tard."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="video_orders",
                to="client_portal.organization",
                verbose_name="Académie / agence liée",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="whatsapp_conversation_date",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Date de création de la conversation WhatsApp",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="deadline_from_whatsapp",
            field=models.BooleanField(
                default=False,
                verbose_name="Deadline automatique : WhatsApp + 5 jours",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="match_package",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (3, "3 matchs — 300 DT"),
                    (5, "5 matchs — 350 DT"),
                    (10, "10 matchs — 400 DT"),
                ],
                null=True,
                verbose_name="Nombre de matchs à traiter",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="matches_processed",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                verbose_name="Nombre de matchs déjà traités",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="delivery_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "Renseignée automatiquement lors du passage à Livrée si elle est vide, "
                    "mais reste modifiable pour corriger une ancienne vidéo."
                ),
                null=True,
                verbose_name="Date réelle de livraison",
            ),
        ),
    ]
