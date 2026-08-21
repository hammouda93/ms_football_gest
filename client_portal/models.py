import hashlib
import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Organization(models.Model):
    class Kind(models.TextChoices):
        AGENT = "agent", "Agence / Agent"
        ACADEMY = "academy", "Académie"
        CLUB = "club", "Club"

    name = models.CharField("Nom", max_length=160)
    kind = models.CharField(
        "Type",
        max_length=20,
        choices=Kind.choices,
        default=Kind.AGENT,
    )
    contact_name = models.CharField("Contact principal", max_length=120, blank=True)
    email = models.EmailField("E-mail", blank=True)
    whatsapp_number = models.CharField("WhatsApp", max_length=24, blank=True)
    country = models.CharField("Pays", max_length=80, blank=True)
    is_active = models.BooleanField("Actif", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_portal_organizations",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Organisation cliente"
        verbose_name_plural = "Organisations clientes"

    def __str__(self):
        return self.name


class PortalProfile(models.Model):
    class AccountType(models.TextChoices):
        PLAYER = "player", "Joueur"
        AGENT = "agent", "Agent"
        ACADEMY = "academy", "Académie / Club"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_profile",
    )
    account_type = models.CharField(
        "Type de compte",
        max_length=20,
        choices=AccountType.choices,
    )
    display_name = models.CharField("Nom affiché", max_length=160)
    whatsapp_number = models.CharField("WhatsApp", max_length=24, blank=True)
    preferred_language = models.CharField(
        "Langue",
        max_length=5,
        choices=(("fr", "Français"), ("en", "English"), ("ar", "العربية")),
        default="fr",
    )
    is_active = models.BooleanField("Accès actif", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_portal_profiles",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_name",)
        verbose_name = "Compte portail"
        verbose_name_plural = "Comptes portail"

    def __str__(self):
        return self.display_name

    @property
    def access_enabled(self):
        return self.is_active and self.user.is_active


class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Responsable"
        STAFF = "staff", "Collaborateur"
        VIEWER = "viewer", "Lecture seule"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="unique_portal_organization_membership",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.organization}"


class OrganizationPlayer(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="player_links",
    )
    player = models.ForeignKey(
        "gestion_joueurs.Player",
        on_delete=models.CASCADE,
        related_name="portal_organization_links",
    )
    label = models.CharField("Référence interne", max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(
        "Fin de la relation",
        null=True,
        blank=True,
        help_text="Renseignée lorsque le joueur n’est plus représenté par cette organisation.",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="added_organization_players",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "player"),
                name="unique_portal_organization_player",
            )
        ]
        ordering = ("player__name",)

    def __str__(self):
        return f"{self.organization} — {self.player}"


class PlayerAccess(models.Model):
    class Role(models.TextChoices):
        PLAYER = "player", "Joueur"
        REPRESENTATIVE = "representative", "Représentant"
        VIEWER = "viewer", "Lecture seule"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_player_accesses",
    )
    player = models.ForeignKey(
        "gestion_joueurs.Player",
        on_delete=models.CASCADE,
        related_name="portal_user_accesses",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PLAYER)
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="granted_player_accesses",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "player"),
                name="unique_portal_user_player_access",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.player}"


class PortalAccessLink(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_access_links",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_portal_access_links",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, *, user, created_by, lifetime):
        raw_token = secrets.token_urlsafe(32)
        link = cls.objects.create(
            user=user,
            token_hash=cls.hash_token(raw_token),
            expires_at=timezone.now() + lifetime,
            created_by=created_by,
        )
        return link, raw_token

    @property
    def is_usable(self):
        try:
            active_profile = self.user.portal_profile.is_active
        except PortalProfile.DoesNotExist:
            active_profile = False
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
            and self.user.is_active
            and active_profile
        )


class VideoWorkflow(models.Model):
    class Stage(models.TextChoices):
        NEW_ORDER = "new_order", "Nouvelle commande"
        AWAITING_DEPOSIT = "awaiting_deposit", "En attente d’acompte"
        AWAITING_MEDIA = "awaiting_media", "Matchs à recevoir"
        DOWNLOADING = "downloading", "Téléchargement SportsBase"
        EDITING = "editing", "Montage en cours"
        CLIENT_REVIEW = "client_review", "Validation client"
        REVISIONS = "revisions", "Corrections demandées"
        AWAITING_BALANCE = "awaiting_balance", "Solde à payer"
        READY_DELIVERY = "ready_delivery", "Prête à livrer"
        DELIVERED = "delivered", "Livrée"
        BLOCKED = "blocked", "Bloquée"

    class Priority(models.TextChoices):
        LOW = "low", "Basse"
        NORMAL = "normal", "Normale"
        HIGH = "high", "Haute"
        URGENT = "urgent", "Urgente"

    video = models.OneToOneField(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="production_workflow",
    )
    stage = models.CharField(max_length=30, choices=Stage.choices)
    priority = models.CharField(
        max_length=12,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    progress = models.PositiveSmallIntegerField(
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(100)),
    )
    next_action = models.CharField(max_length=240, blank=True)
    blocked_reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="updated_video_workflows",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("video__deadline", "-priority")

    def __str__(self):
        return f"{self.video} — {self.get_stage_display()}"


class VideoActivity(models.Model):
    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        STAGE = "stage", "Étape"
        MEDIA = "media", "Média"
        VERSION = "version", "Version"
        REVIEW = "review", "Validation / correction"
        PAYMENT = "payment", "Paiement"
        MESSAGE = "message", "Communication"

    class Visibility(models.TextChoices):
        INTERNAL = "internal", "Interne"
        CLIENT = "client", "Visible par le client"

    video = models.ForeignKey(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="portal_activities",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NOTE)
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.INTERNAL,
    )
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="portal_video_activities",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.video_id} — {self.message[:60]}"


class MediaSubmission(models.Model):
    class Category(models.TextChoices):
        MATCH = "match", "Match complet"
        ACTION = "action", "Action individuelle"
        STATISTICS = "statistics", "Statistiques"
        PHOTO = "photo", "Photo / identité visuelle"
        DOCUMENT = "document", "Document"
        OTHER = "other", "Autre"

    class Status(models.TextChoices):
        NEW = "new", "Nouveau"
        REVIEWED = "reviewed", "Vérifié"
        ACCEPTED = "accepted", "Accepté"
        REJECTED = "rejected", "À remplacer"

    video = models.ForeignKey(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="media_submissions",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    title = models.CharField(max_length=160)
    source_url = models.URLField("Lien du fichier ou du match")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="portal_media_submissions",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_portal_media_submissions",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class VideoVersion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "À valider"
        CHANGES_REQUESTED = "changes_requested", "Corrections demandées"
        APPROVED = "approved", "Approuvée"
        REPLACED = "replaced", "Remplacée"

    video = models.ForeignKey(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="portal_versions",
    )
    version_number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160, blank=True)
    preview_url = models.URLField("Lien de prévisualisation")
    final_url = models.URLField("Lien final", blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="uploaded_portal_versions",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_portal_versions",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("video", "version_number"),
                name="unique_portal_video_version_number",
            )
        ]
        ordering = ("-version_number",)

    def __str__(self):
        return self.title or f"Version {self.version_number}"


class RevisionRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "À traiter"
        IN_PROGRESS = "in_progress", "En cours"
        RESOLVED = "resolved", "Résolue"
        REJECTED = "rejected", "Non retenue"

    version = models.ForeignKey(
        VideoVersion,
        on_delete=models.CASCADE,
        related_name="revision_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_portal_revisions",
        null=True,
        blank=True,
    )
    timecode_seconds = models.PositiveIntegerField(null=True, blank=True)
    comment = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    staff_response = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_portal_revisions",
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "timecode_seconds", "created_at")

    def __str__(self):
        return f"{self.version} — {self.comment[:60]}"


class PaymentRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        OPENED = "opened", "Lien ouvert"
        PAID = "paid", "Payée"
        CANCELLED = "cancelled", "Annulée"
        EXPIRED = "expired", "Expirée"

    video = models.ForeignKey(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="portal_payment_requests",
    )
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    payment_url = models.URLField(
        "Lien de paiement",
        blank=True,
        help_text="Lien créé chez le prestataire de paiement choisi.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_portal_payment_requests",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.label} — {self.amount}"


class CommunicationLog(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "E-mail"
        PORTAL = "portal", "Portail"

    class State(models.TextChoices):
        DRAFT_OPENED = "draft_opened", "Brouillon ouvert"
        SENT = "sent", "Envoyé"
        DELIVERED = "delivered", "Livré"
        FAILED = "failed", "Échec"
        RECEIVED = "received", "Reçu"

    video = models.ForeignKey(
        "gestion_joueurs.Video",
        on_delete=models.CASCADE,
        related_name="communication_logs",
        null=True,
        blank=True,
    )
    player = models.ForeignKey(
        "gestion_joueurs.Player",
        on_delete=models.CASCADE,
        related_name="communication_logs",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    template_key = models.CharField(max_length=40, blank=True)
    recipient = models.CharField(max_length=180, blank=True)
    message = models.TextField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT_OPENED)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="portal_communications",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_channel_display()} — {self.recipient}"


class AgentPlayerRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Nouvelle"
        REVIEWING = "reviewing", "En vérification"
        LINKED = "linked", "Joueur associé"
        REJECTED = "rejected", "Refusée"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="player_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="portal_agent_player_requests",
        null=True,
        blank=True,
    )
    full_name = models.CharField("Nom du joueur", max_length=160)
    transfermarkt_url = models.URLField("Lien Transfermarkt", blank=True)
    club = models.CharField("Club", max_length=120, blank=True)
    whatsapp_number = models.CharField("WhatsApp", max_length=24, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    linked_player = models.ForeignKey(
        "gestion_joueurs.Player",
        on_delete=models.SET_NULL,
        related_name="portal_agent_requests",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_portal_agent_requests",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.full_name} — {self.organization}"
