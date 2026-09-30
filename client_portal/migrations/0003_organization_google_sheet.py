from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("client_portal", "0002_organizationplayer_ended_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="google_sheet_id",
            field=models.CharField(
                blank=True,
                help_text="ID du fichier Google Sheet associé à cette organisation.",
                max_length=255,
                verbose_name="Google Sheet ID",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_sheet_tab",
            field=models.CharField(
                blank=True,
                default="Players",
                max_length=100,
                verbose_name="Onglet Google Sheet",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_sheet_last_synced_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Dernière synchronisation Google Sheet",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="google_sheet_last_error",
            field=models.TextField(
                blank=True,
                verbose_name="Dernière erreur Google Sheet",
            ),
        ),
    ]
