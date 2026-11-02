from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("client_portal", "0003_organization_google_sheet"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationplayer",
            name="expected_matches",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (3, "3 matchs"),
                    (5, "5 matchs"),
                    (10, "10 matchs"),
                ],
                help_text=(
                    "Planification de l’académie, distincte des matchs "
                    "envoyés par le joueur."
                ),
                null=True,
                verbose_name="Nombre de matchs attendus par l’organisation",
            ),
        ),
    ]
