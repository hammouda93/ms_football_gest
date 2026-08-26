from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("sportsbase_data", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsbasesubscription",
            name="youtube_delivery_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "L’agent local publie la vidéo sur la chaîne configurée et ajoute "
                    "le lecteur au portail client."
                ),
                verbose_name="Publier All Actions sur YouTube (non répertoriée)",
            ),
        ),
        migrations.AddField(
            model_name="sportsbasesubscription",
            name="report_language",
            field=models.CharField(
                choices=[
                    ("fr", "Français"),
                    ("en", "English"),
                    ("ar", "العربية"),
                ],
                default="fr",
                max_length=5,
                verbose_name="Langue du portail et des rapports",
            ),
        ),
        migrations.CreateModel(
            name="SportsBaseYouTubeUpload",
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
                            ("running", "Upload en cours"),
                            ("uploaded", "Vidéo disponible"),
                            ("failed", "Échec"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("upload_title", models.CharField(blank=True, max_length=100)),
                ("youtube_url", models.URLField(blank=True)),
                (
                    "youtube_video_id",
                    models.CharField(blank=True, db_index=True, max_length=32),
                ),
                (
                    "content_sha256",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("file_size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("notification_sent_at", models.DateTimeField(blank=True, null=True)),
                ("notification_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "match",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="youtube_upload",
                        to="sportsbase_data.sportsbasematch",
                    ),
                ),
            ],
            options={
                "verbose_name": "Publication YouTube All Actions",
                "verbose_name_plural": "Publications YouTube All Actions",
                "ordering": ("-match__match_date", "created_at"),
            },
        ),
        migrations.CreateModel(
            name="PerformanceReport",
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
                    "report_type",
                    models.CharField(
                        choices=[
                            ("match", "Rapport de match"),
                            ("cycle", "Rapport de cycle (5 matchs)"),
                        ],
                        max_length=12,
                    ),
                ),
                ("cycle_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "language",
                    models.CharField(
                        choices=[
                            ("fr", "Français"),
                            ("en", "English"),
                            ("ar", "العربية"),
                        ],
                        default="fr",
                        max_length=5,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Brouillon"), ("published", "Publié")],
                        db_index=True,
                        default="published",
                        max_length=12,
                    ),
                ),
                ("title", models.CharField(max_length=220)),
                ("executive_summary", models.TextField(blank=True)),
                ("strengths", models.TextField(blank=True)),
                ("improvement_areas", models.TextField(blank=True)),
                ("analyst_notes", models.TextField(blank=True)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("match_ids", models.JSONField(blank=True, default=list)),
                ("is_manually_edited", models.BooleanField(default=False)),
                ("generated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "match",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_report",
                        to="sportsbase_data.sportsbasematch",
                    ),
                ),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performance_reports",
                        to="sportsbase_data.sportsbasesubscription",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_performance_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Rapport de performance",
                "verbose_name_plural": "Rapports de performance",
                "ordering": ("-generated_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="performancereport",
            constraint=models.UniqueConstraint(
                fields=("subscription", "report_type", "cycle_number"),
                name="unique_performance_cycle_report",
            ),
        ),
    ]
