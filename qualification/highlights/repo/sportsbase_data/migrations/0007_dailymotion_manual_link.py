from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sportsbase_data", "0006_dailymotion_all_actions_fallback"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sportsbasedailymotionupload",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "En attente"),
                    ("running", "Upload Dailymotion en cours"),
                    ("link_pending", "Upload effectué — lien à ajouter"),
                    ("uploaded", "Vidéo disponible"),
                    ("failed", "Échec"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
    ]
