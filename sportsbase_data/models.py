from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class SportsBaseSubscription(models.Model):
    class ReportLanguage(models.TextChoices):
        FRENCH = "fr", "Français"
        ENGLISH = "en", "English"
        ARABIC = "ar", "العربية"

    class SyncState(models.TextChoices):
        NEVER = "never", "Jamais synchronisé"
        QUEUED = "queued", "En attente"
        RUNNING = "running", "Synchronisation en cours"
        SUCCESS = "success", "À jour"
        PARTIAL = "partial", "Partiellement synchronisé"
        FAILED = "failed", "Échec"

    player = models.OneToOneField(
        "gestion_joueurs.Player",
        on_delete=models.CASCADE,
        related_name="sportsbase_subscription",
        verbose_name="Joueur",
    )
    is_active = models.BooleanField("Abonnement actif", default=True)
    season = models.CharField("Saison actuelle", max_length=20)
    starts_on = models.DateField("Début de l’abonnement", default=timezone.localdate)
    ends_on = models.DateField("Fin de l’abonnement", null=True, blank=True)
    sync_from_date = models.DateField(
        "Importer à partir de la date",
        null=True,
        blank=True,
        help_text="Facultatif : ignore les rencontres plus anciennes.",
    )
    first_match_id = models.CharField(
        "Premier identifiant de match SportsBase",
        max_length=32,
        blank=True,
        help_text="Facultatif : ce match devient le début de la saison à importer.",
    )
    all_actions_enabled = models.BooleanField(
        "Télécharger All Actions",
        default=True,
    )
    email_delivery_enabled = models.BooleanField(
        "Envoyer All Actions par e-mail",
        default=True,
    )
    youtube_delivery_enabled = models.BooleanField(
        "Publier All Actions sur YouTube (non répertoriée)",
        default=False,
        help_text=(
            "L’agent local publie la vidéo sur la chaîne configurée et ajoute le "
            "lecteur au portail client."
        ),
    )
    report_language = models.CharField(
        "Langue du portail et des rapports",
        max_length=5,
        choices=ReportLanguage.choices,
        default=ReportLanguage.FRENCH,
    )
    sync_interval_hours = models.PositiveSmallIntegerField(
        "Intervalle de synchronisation (heures)",
        default=24,
        validators=(MinValueValidator(1),),
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_state = models.CharField(
        max_length=16,
        choices=SyncState.choices,
        default=SyncState.NEVER,
    )
    last_error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_sportsbase_subscriptions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("player__name",)
        verbose_name = "Abonnement Performance"
        verbose_name_plural = "Abonnements Performance"

    def __str__(self):
        return f"{self.player} — {self.season}"

    def clean(self):
        super().clean()
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError(
                {"ends_on": "La date de fin doit être postérieure à la date de début."}
            )
        if self.first_match_id and not self.first_match_id.isdigit():
            raise ValidationError(
                {"first_match_id": "Utilisez uniquement l’identifiant numérique du match."}
            )
        player = getattr(self, "player", None)
        if self.is_active and player and not player.sportsbase_url:
            raise ValidationError(
                {"player": "Le joueur doit posséder une adresse de profil SportsBase."}
            )

    @property
    def access_enabled(self):
        today = timezone.localdate()
        return (
            self.is_active
            and self.starts_on <= today
            and (self.ends_on is None or self.ends_on >= today)
        )


class SportsBaseSeasonSnapshot(models.Model):
    subscription = models.ForeignKey(
        SportsBaseSubscription,
        on_delete=models.CASCADE,
        related_name="season_snapshots",
    )
    season = models.CharField(max_length=20)
    sportsbase_player_id = models.CharField(max_length=32, blank=True, db_index=True)
    sportsbase_player_name = models.CharField(max_length=160, blank=True)
    native_name = models.CharField(max_length=160, blank=True)
    club_name = models.CharField(max_length=160, blank=True)
    club_sportsbase_id = models.CharField(max_length=32, blank=True)
    profile_image_url = models.URLField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    contract_expires = models.DateField(null=True, blank=True)
    height_weight = models.CharField(max_length=100, blank=True)
    national_team = models.CharField(max_length=160, blank=True)
    strong_foot = models.CharField(max_length=80, blank=True)
    time_on_field_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    positions = models.JSONField(default=list, blank=True)
    season_statistics = models.JSONField(default=dict, blank=True)
    average_statistics = models.JSONField(default=dict, blank=True)
    season_table_headers = models.JSONField(default=list, blank=True)
    season_match_rows = models.JSONField(default=list, blank=True)
    radar_metrics = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    radar_png = models.BinaryField(null=True, blank=True, editable=False)
    heatmap_png = models.BinaryField(null=True, blank=True, editable=False)
    ball_touches_png = models.BinaryField(null=True, blank=True, editable=False)
    maps_captured_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "season"),
                name="unique_sportsbase_subscription_season",
            )
        ]
        ordering = ("-season",)

    def __str__(self):
        return f"{self.subscription.player} — {self.season}"


class SportsBaseMatch(models.Model):
    class SyncState(models.TextChoices):
        DISCOVERED = "discovered", "Détecté"
        SYNCED = "synced", "Statistiques synchronisées"
        PARTIAL = "partial", "Données partielles"
        FAILED = "failed", "Erreur"

    class ActionsState(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Non demandé"
        QUEUED = "queued", "À générer"
        GENERATING = "generating", "Génération SportsBase"
        DOWNLOADED = "downloaded", "Téléchargé localement"
        EMAILED = "emailed", "Envoyé par e-mail"
        FAILED = "failed", "Erreur"

    subscription = models.ForeignKey(
        SportsBaseSubscription,
        on_delete=models.CASCADE,
        related_name="matches",
    )
    sportsbase_match_id = models.CharField(max_length=32)
    season = models.CharField(max_length=20)
    match_date = models.DateField(null=True, blank=True, db_index=True)
    competition = models.CharField(max_length=160, blank=True)
    week = models.CharField(max_length=80, blank=True)
    referee = models.CharField(max_length=160, blank=True)
    home_team = models.CharField(max_length=160, blank=True)
    home_team_id = models.CharField(max_length=32, blank=True)
    away_team = models.CharField(max_length=160, blank=True)
    away_team_id = models.CharField(max_length=32, blank=True)
    home_score = models.SmallIntegerField(null=True, blank=True)
    away_score = models.SmallIntegerField(null=True, blank=True)
    lineup = models.CharField(max_length=80, blank=True)
    match_url = models.URLField(blank=True)
    sync_state = models.CharField(
        max_length=16,
        choices=SyncState.choices,
        default=SyncState.DISCOVERED,
    )
    actions_state = models.CharField(
        max_length=20,
        choices=ActionsState.choices,
        default=ActionsState.NOT_REQUESTED,
    )
    local_folder_key = models.CharField(max_length=255, blank=True)
    all_actions_filename = models.CharField(max_length=255, blank=True)
    all_actions_downloaded_at = models.DateTimeField(null=True, blank=True)
    all_actions_emailed_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "sportsbase_match_id"),
                name="unique_sportsbase_match_per_subscription",
            )
        ]
        ordering = ("-match_date", "-sportsbase_match_id")

    def __str__(self):
        return f"{self.home_team} — {self.away_team} ({self.match_date or 'date inconnue'})"

    @property
    def score(self):
        if self.home_score is None or self.away_score is None:
            return "–"
        return f"{self.home_score}–{self.away_score}"

    @property
    def is_complete(self):
        stats_complete = self.sync_state == self.SyncState.SYNCED
        if not self.subscription.all_actions_enabled:
            return stats_complete
        if self.subscription.youtube_delivery_enabled:
            return stats_complete and self.actions_state in {
                self.ActionsState.DOWNLOADED,
                self.ActionsState.EMAILED,
            }
        if self.subscription.email_delivery_enabled:
            return stats_complete and self.actions_state == self.ActionsState.EMAILED
        return stats_complete and self.actions_state in {
            self.ActionsState.DOWNLOADED,
            self.ActionsState.EMAILED,
        }


class SportsBaseMatchStats(models.Model):
    match = models.OneToOneField(
        SportsBaseMatch,
        on_delete=models.CASCADE,
        related_name="player_stats",
    )
    team_name = models.CharField(max_length=160, blank=True)
    position = models.CharField(max_length=80, blank=True)
    position_percentages = models.JSONField(default=list, blank=True)
    minutes_played = models.PositiveSmallIntegerField(null=True, blank=True)
    index = models.IntegerField(null=True, blank=True)
    team_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    match_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    summary_statistics = models.JSONField(default=dict, blank=True)
    success_rates = models.JSONField(default=dict, blank=True)
    detailed_statistics = models.JSONField(default=dict, blank=True)
    team_table = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    heatmap_png = models.BinaryField(null=True, blank=True, editable=False)
    ball_touches_png = models.BinaryField(null=True, blank=True, editable=False)
    maps_captured_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Statistiques SportsBase du match"
        verbose_name_plural = "Statistiques SportsBase des matchs"

    def __str__(self):
        return f"Statistiques — {self.match}"


class SportsBaseSyncJob(models.Model):
    class JobType(models.TextChoices):
        FULL = "full", "Profil, saison, matchs et All Actions"
        PROFILE = "profile", "Profil et saison"
        MATCHES = "matches", "Matchs et statistiques"
        ALL_ACTIONS = "all_actions", "All Actions manquants"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        RUNNING = "running", "En cours"
        SUCCESS = "success", "Terminé"
        PARTIAL = "partial", "Partiel"
        FAILED = "failed", "Échec"

    subscription = models.ForeignKey(
        SportsBaseSubscription,
        on_delete=models.CASCADE,
        related_name="sync_jobs",
    )
    job_type = models.CharField(
        max_length=20,
        choices=JobType.choices,
        default=JobType.FULL,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_sportsbase_sync_jobs",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.subscription.player} — {self.get_job_type_display()} — {self.get_status_display()}"


class SportsBaseYouTubeUpload(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        RUNNING = "running", "Upload en cours"
        UPLOADED = "uploaded", "Vidéo disponible"
        FAILED = "failed", "Échec"

    match = models.OneToOneField(
        SportsBaseMatch,
        on_delete=models.CASCADE,
        related_name="youtube_upload",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    upload_title = models.CharField(max_length=100, blank=True)
    youtube_url = models.URLField(blank=True)
    youtube_video_id = models.CharField(max_length=32, blank=True, db_index=True)
    content_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    file_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    notification_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-match__match_date", "created_at")
        verbose_name = "Publication YouTube All Actions"
        verbose_name_plural = "Publications YouTube All Actions"

    def __str__(self):
        return f"{self.match.subscription.player} — {self.match} — {self.get_status_display()}"


class PerformanceReport(models.Model):
    class ReportType(models.TextChoices):
        MATCH = "match", "Rapport de match"
        CYCLE = "cycle", "Rapport de cycle (5 matchs)"

    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        PUBLISHED = "published", "Publié"

    subscription = models.ForeignKey(
        SportsBaseSubscription,
        on_delete=models.CASCADE,
        related_name="performance_reports",
    )
    match = models.OneToOneField(
        SportsBaseMatch,
        on_delete=models.CASCADE,
        related_name="performance_report",
        null=True,
        blank=True,
    )
    report_type = models.CharField(max_length=12, choices=ReportType.choices)
    cycle_number = models.PositiveSmallIntegerField(null=True, blank=True)
    language = models.CharField(
        max_length=5,
        choices=SportsBaseSubscription.ReportLanguage.choices,
        default=SportsBaseSubscription.ReportLanguage.FRENCH,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
    )
    title = models.CharField(max_length=220)
    executive_summary = models.TextField(blank=True)
    strengths = models.TextField(blank=True)
    improvement_areas = models.TextField(blank=True)
    analyst_notes = models.TextField(blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    match_ids = models.JSONField(default=list, blank=True)
    is_manually_edited = models.BooleanField(default=False)
    generated_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    notification_error = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="updated_performance_reports",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-generated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "report_type", "cycle_number"),
                name="unique_performance_cycle_report",
            )
        ]
        verbose_name = "Rapport de performance"
        verbose_name_plural = "Rapports de performance"

    def __str__(self):
        return self.title
