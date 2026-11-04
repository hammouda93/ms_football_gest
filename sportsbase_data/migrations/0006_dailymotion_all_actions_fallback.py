from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("sportsbase_data", "0005_performance_subscription_payments"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsBaseDailymotionUpload",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "En attente"),
                            ("running", "Upload Dailymotion en cours"),
                            ("uploaded", "Vidéo disponible"),
                            ("failed", "Échec"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("upload_title", models.CharField(blank=True, max_length=255)),
                ("dailymotion_url", models.URLField(blank=True)),
                (
                    "dailymotion_video_id",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                (
                    "content_sha256",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("file_size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "match",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dailymotion_upload",
                        to="sportsbase_data.sportsbasematch",
                    ),
                ),
            ],
            options={
                "verbose_name": "Publication Dailymotion All Actions",
                "verbose_name_plural": "Publications Dailymotion All Actions",
                "ordering": ("-match__match_date", "created_at"),
            },
        ),
    ]
