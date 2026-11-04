from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestion_joueurs", "0057_automationrun_automationevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="video",
            name="intro_presentation_style",
            field=models.CharField(
                choices=[
                    ("stadium_golden_hour", "Stade — Golden Hour"),
                    ("stadium_night", "Stade de nuit"),
                    ("training_ground", "Terrain d’entraînement"),
                    ("modern_stands", "Tribunes modernes"),
                    ("player_tunnel", "Tunnel des joueurs"),
                    ("premium_locker_room", "Vestiaire premium"),
                    ("official_club_studio", "Studio officiel du club"),
                    ("dark_cinema_studio", "Studio cinéma sombre"),
                    ("press_room", "Salle de conférence"),
                    ("country_city_identity", "Identité pays / ville"),
                ],
                default="stadium_golden_hour",
                max_length=40,
                verbose_name="Style de présentation",
            ),
        ),
    ]
