import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.template.defaultfilters import slugify
from django.utils.crypto import get_random_string
from django.utils import timezone

from gestion_joueurs.models import Invoice, Player, Video

from .models import (
    CommunicationLog,
    OrganizationMembership,
    OrganizationPlayer,
    PlayerAccess,
    PortalAccessLink,
    PortalProfile,
    RevisionRequest,
    VideoActivity,
    VideoWorkflow,
)


User = get_user_model()


@dataclass(frozen=True)
class InvoiceSnapshot:
    total: Decimal
    paid: Decimal
    balance: Decimal
    status: str


@dataclass(frozen=True)
class PortalCredentialDelivery:
    email_sent: bool
    email_error: bool
    whatsapp_url: str


@dataclass(frozen=True)
class ClientTimelineEvent:
    kind: str
    tone: str
    icon: str
    title: str
    message: str
    occurred_at: date | datetime
    has_time: bool
    sort_at: datetime


PORTAL_ACCESS_LINK_LIFETIME = timedelta(days=365)


CLIENT_COMPLETED_COLLAB_LABEL = (
    "En cours de finition et classification des séquences"
)


CLIENT_STATUS_TITLES = {
    Video.StatusChoices.PENDING: "Commande enregistrée",
    Video.StatusChoices.IN_PROGRESS: "Production démarrée",
    Video.StatusChoices.COMPLETED_COLLAB: CLIENT_COMPLETED_COLLAB_LABEL,
    Video.StatusChoices.COMPLETED: "Montage terminé",
    Video.StatusChoices.DELIVERED: "Vidéo livrée",
    Video.StatusChoices.PROBLEMATIC: "Vérification complémentaire",
}


CLIENT_STATUS_ICONS = {
    Video.StatusChoices.PENDING: "fa-clipboard-check",
    Video.StatusChoices.IN_PROGRESS: "fa-clapperboard",
    Video.StatusChoices.COMPLETED_COLLAB: "fa-wand-magic-sparkles",
    Video.StatusChoices.COMPLETED: "fa-circle-check",
    Video.StatusChoices.DELIVERED: "fa-circle-play",
    Video.StatusChoices.PROBLEMATIC: "fa-magnifying-glass",
}


PAYMENT_EVENT_TITLES = {
    "advance": "Acompte enregistré",
    "partial": "Paiement partiel enregistré",
    "final": "Paiement final enregistré",
}


PAYMENT_METHOD_LABELS = {
    "cash": "espèces",
    "bank_transfer": "virement bancaire",
    "la_poste": "La Poste",
}


ACTIVITY_ICONS = {
    VideoActivity.Kind.NOTE: "fa-note-sticky",
    VideoActivity.Kind.STAGE: "fa-route",
    VideoActivity.Kind.MEDIA: "fa-link",
    VideoActivity.Kind.VERSION: "fa-film",
    VideoActivity.Kind.REVIEW: "fa-comments",
    VideoActivity.Kind.PAYMENT: "fa-wallet",
    VideoActivity.Kind.MESSAGE: "fa-message",
}


STAGE_PROGRESS = {
    VideoWorkflow.Stage.NEW_ORDER: 5,
    VideoWorkflow.Stage.AWAITING_DEPOSIT: 10,
    VideoWorkflow.Stage.AWAITING_MEDIA: 20,
    VideoWorkflow.Stage.DOWNLOADING: 35,
    VideoWorkflow.Stage.EDITING: 55,
    VideoWorkflow.Stage.CLIENT_REVIEW: 75,
    VideoWorkflow.Stage.REVISIONS: 82,
    VideoWorkflow.Stage.AWAITING_BALANCE: 90,
    VideoWorkflow.Stage.READY_DELIVERY: 95,
    VideoWorkflow.Stage.DELIVERED: 100,
    VideoWorkflow.Stage.BLOCKED: 0,
}


STAGE_NEXT_ACTION = {
    VideoWorkflow.Stage.NEW_ORDER: "Qualifier la commande et confirmer le prix.",
    VideoWorkflow.Stage.AWAITING_DEPOSIT: "Confirmer ou demander l’acompte.",
    VideoWorkflow.Stage.AWAITING_MEDIA: "Recevoir les matchs et actions du joueur.",
    VideoWorkflow.Stage.DOWNLOADING: "Contrôler le téléchargement SportsBase.",
    VideoWorkflow.Stage.EDITING: "Poursuivre le montage et préparer une version.",
    VideoWorkflow.Stage.CLIENT_REVIEW: "Obtenir la validation du joueur ou de l’agent.",
    VideoWorkflow.Stage.REVISIONS: "Traiter les corrections ouvertes.",
    VideoWorkflow.Stage.AWAITING_BALANCE: "Demander le paiement du solde.",
    VideoWorkflow.Stage.READY_DELIVERY: "Vérifier le fichier final et le livrer.",
    VideoWorkflow.Stage.DELIVERED: "Planifier une relance ou une mise à jour future.",
    VideoWorkflow.Stage.BLOCKED: "Résoudre le blocage indiqué.",
}


def invoice_snapshot(video):
    try:
        invoice = video.invoices
    except Invoice.DoesNotExist:
        invoice = None

    if invoice:
        total = Decimal(invoice.total_amount or 0)
        paid = Decimal(invoice.amount_paid or 0)
        status = invoice.status
    else:
        total = Decimal(video.total_payment or 0)
        paid = Decimal(video.advance_payment or 0)
        status = "paid" if total > 0 and paid >= total else "unpaid"

    return InvoiceSnapshot(
        total=total,
        paid=paid,
        balance=max(total - paid, Decimal("0")),
        status=status,
    )


def _timeline_datetime(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.combine(value, time.min)
    if timezone.is_naive(result):
        return timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _client_status_message(video, status):
    deadline = video.deadline.strftime("%d/%m/%Y")
    messages = {
        Video.StatusChoices.PENDING: (
            "La commande est enregistrée et attend le démarrage de la production."
        ),
        Video.StatusChoices.IN_PROGRESS: (
            f"Le montage est en cours. La livraison est prévue le {deadline}."
        ),
        Video.StatusChoices.COMPLETED_COLLAB: (
            "Les premières étapes du montage sont terminées. Notre équipe finalise "
            "la vidéo et classe les séquences sélectionnées."
        ),
        Video.StatusChoices.COMPLETED: (
            "Le montage est terminé et passe aux dernières vérifications avant livraison."
        ),
        Video.StatusChoices.DELIVERED: (
            "La vidéo finale a été livrée et reste disponible dans votre espace."
        ),
        Video.StatusChoices.PROBLEMATIC: (
            "Une vérification complémentaire est en cours sur la production."
        ),
    }
    return messages.get(status, "L’état de la production a été mis à jour.")


def client_video_timeline(video, activities=()):
    """Build a client-facing timeline without writing or altering legacy data."""
    events = []

    for history in video.status_history.order_by("changed_at", "pk"):
        occurred_at = history.changed_at
        events.append(
            ClientTimelineEvent(
                kind="status",
                tone=history.status,
                icon=CLIENT_STATUS_ICONS.get(history.status, "fa-route"),
                title=CLIENT_STATUS_TITLES.get(
                    history.status,
                    "État de la vidéo mis à jour",
                ),
                message=_client_status_message(video, history.status),
                occurred_at=occurred_at,
                has_time=True,
                sort_at=_timeline_datetime(occurred_at),
            )
        )

    for payment in video.payments.order_by("payment_date", "pk"):
        occurred_at = payment.payment_date
        payment_method = PAYMENT_METHOD_LABELS.get(payment.payment_method)
        method_text = f" via {payment_method}" if payment_method else ""
        if payment.remaining_balance > 0:
            balance_text = (
                f" Solde restant après ce règlement : "
                f"{payment.remaining_balance:.2f}."
            )
        elif payment.payment_type == "final":
            balance_text = " La commande est entièrement réglée."
        else:
            balance_text = ""
        events.append(
            ClientTimelineEvent(
                kind="payment",
                tone="payment",
                icon="fa-wallet",
                title=PAYMENT_EVENT_TITLES.get(
                    payment.payment_type,
                    "Paiement enregistré",
                ),
                message=(
                    f"Un paiement de {payment.amount:.2f} a été enregistré"
                    f"{method_text}.{balance_text}"
                ),
                occurred_at=occurred_at,
                has_time=False,
                sort_at=_timeline_datetime(occurred_at),
            )
        )

    for activity in activities:
        occurred_at = activity.created_at
        events.append(
            ClientTimelineEvent(
                kind="activity",
                tone=activity.kind,
                icon=ACTIVITY_ICONS.get(activity.kind, "fa-bell"),
                title=activity.get_kind_display(),
                message=activity.message,
                occurred_at=occurred_at,
                has_time=True,
                sort_at=_timeline_datetime(occurred_at),
            )
        )

    events.sort(key=lambda event: event.sort_at, reverse=True)
    return events[:60]


def _saved_workflow(video):
    try:
        return video.production_workflow
    except VideoWorkflow.DoesNotExist:
        return None


def derived_stage(video):
    workflow = _saved_workflow(video)
    if workflow:
        return workflow.stage

    payment = invoice_snapshot(video)
    if video.status == Video.StatusChoices.PROBLEMATIC:
        return VideoWorkflow.Stage.BLOCKED
    if video.status == Video.StatusChoices.DELIVERED:
        return VideoWorkflow.Stage.DELIVERED
    if video.status == Video.StatusChoices.COMPLETED:
        if payment.balance > 0:
            return VideoWorkflow.Stage.AWAITING_BALANCE
        return VideoWorkflow.Stage.READY_DELIVERY
    if video.status == Video.StatusChoices.COMPLETED_COLLAB:
        return VideoWorkflow.Stage.CLIENT_REVIEW
    if video.status == Video.StatusChoices.IN_PROGRESS:
        if video.automation_started and not video.automation_completed:
            return VideoWorkflow.Stage.DOWNLOADING
        return VideoWorkflow.Stage.EDITING
    if payment.total > 0 and payment.paid <= 0:
        return VideoWorkflow.Stage.AWAITING_DEPOSIT
    return VideoWorkflow.Stage.AWAITING_MEDIA


def decorate_video(video):
    workflow = _saved_workflow(video)
    stage = workflow.stage if workflow else derived_stage(video)
    payment = invoice_snapshot(video)
    video.production_stage = stage
    video.production_stage_label = dict(VideoWorkflow.Stage.choices)[stage]
    video.production_progress = (
        workflow.progress if workflow else STAGE_PROGRESS.get(stage, 0)
    )
    video.production_priority = (
        workflow.priority if workflow else VideoWorkflow.Priority.NORMAL
    )
    video.production_next_action = (
        workflow.next_action
        if workflow and workflow.next_action
        else STAGE_NEXT_ACTION.get(stage, "")
    )
    if video.status == Video.StatusChoices.COMPLETED_COLLAB:
        video.production_stage_label = CLIENT_COMPLETED_COLLAB_LABEL
        if not workflow or not workflow.next_action:
            video.production_next_action = (
                "Notre équipe finalise le montage et classe les séquences sélectionnées."
            )
    video.production_blocked_reason = workflow.blocked_reason if workflow else ""
    video.payment_snapshot = payment
    video.final_delivery_available = bool(
        video.status == Video.StatusChoices.DELIVERED
        and video.video_link
        and payment.balance <= 0
    )
    video.is_late = (
        video.deadline < timezone.localdate()
        and stage != VideoWorkflow.Stage.DELIVERED
    )
    return video


def production_queryset_for(user):
    queryset = Video.objects.select_related(
        "player",
        "editor__user",
        "production_workflow",
        "invoices",
    ).prefetch_related("portal_versions__revision_requests")
    if user.is_superuser:
        return queryset
    try:
        editor = user.videoeditor
    except Exception:
        return queryset.none()
    return queryset.filter(editor=editor)


def accessible_players_for(user):
    if not user.is_authenticated:
        return Player.objects.none()
    direct = Q(
        portal_user_accesses__user=user,
        portal_user_accesses__is_active=True,
    )
    through_organization = Q(
        portal_organization_links__is_active=True,
        portal_organization_links__organization__is_active=True,
        portal_organization_links__organization__memberships__user=user,
        portal_organization_links__organization__memberships__is_active=True,
    )
    return Player.objects.filter(direct | through_organization).distinct()


def accessible_videos_for(user):
    return Video.objects.filter(
        player__in=accessible_players_for(user),
        client_portal_visible=True,
    ).select_related(
        "player",
        "editor__user",
        "production_workflow",
        "invoices",
    ).prefetch_related(
        "media_submissions",
        "portal_versions__revision_requests",
        "portal_payment_requests",
    ).distinct()


def editable_players_for(user):
    """Players for which a portal user may submit or approve client actions."""
    if not user.is_authenticated:
        return Player.objects.none()
    direct = Q(
        portal_user_accesses__user=user,
        portal_user_accesses__is_active=True,
        portal_user_accesses__role__in={
            PlayerAccess.Role.PLAYER,
            PlayerAccess.Role.REPRESENTATIVE,
        },
    )
    through_organization = Q(
        portal_organization_links__is_active=True,
        portal_organization_links__organization__is_active=True,
        portal_organization_links__organization__memberships__user=user,
        portal_organization_links__organization__memberships__is_active=True,
        portal_organization_links__organization__memberships__role__in={
            OrganizationMembership.Role.OWNER,
            OrganizationMembership.Role.STAFF,
        },
    )
    return Player.objects.filter(direct | through_organization).distinct()


def editable_videos_for(user):
    return Video.objects.filter(
        player__in=editable_players_for(user),
        client_portal_visible=True,
    ).distinct()


def user_can_access_video(user, video):
    return accessible_players_for(user).filter(pk=video.player_id).exists()


def unique_portal_username(email, display_name):
    seed = email.split("@", 1)[0] if email else display_name
    base = slugify(seed).replace("-", "_")[:120] or "client"
    candidate = f"portal_{base}"
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"portal_{base}_{suffix}"
    return candidate


def generate_temporary_password():
    return f"Mf!{get_random_string(13, allowed_chars='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789')}"


@transaction.atomic
def create_portal_account(cleaned_data, *, created_by, initial_password=None):
    user = User(
        username=unique_portal_username(
            cleaned_data["email"],
            cleaned_data["display_name"],
        ),
        email=cleaned_data["email"],
        first_name=cleaned_data["display_name"][:150],
        is_active=True,
    )
    if initial_password:
        user.set_password(initial_password)
    else:
        user.set_unusable_password()
    user.save()
    profile = PortalProfile.objects.create(
        user=user,
        account_type=cleaned_data["account_type"],
        display_name=cleaned_data["display_name"],
        whatsapp_number=cleaned_data.get("whatsapp_number", ""),
        preferred_language=cleaned_data.get("preferred_language", "fr"),
        created_by=created_by,
    )

    player = cleaned_data.get("player")
    organization = cleaned_data.get("organization")
    if player:
        PlayerAccess.objects.create(
            user=user,
            player=player,
            role=PlayerAccess.Role.PLAYER,
            granted_by=created_by,
        )
    if organization:
        OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        for linked_player in cleaned_data.get("players") or ():
            OrganizationPlayer.objects.update_or_create(
                organization=organization,
                player=linked_player,
                defaults={
                    "is_active": True,
                    "ended_at": None,
                    "added_by": created_by,
                },
            )
    return profile


def provision_portal_account(cleaned_data, *, created_by):
    temporary_password = generate_temporary_password()
    profile = create_portal_account(
        cleaned_data,
        created_by=created_by,
        initial_password=temporary_password,
    )
    return profile, temporary_password


@transaction.atomic
def ensure_player_portal_account(player, *, created_by):
    existing_access = (
        PlayerAccess.objects.select_related("user__portal_profile")
        .filter(
            player=player,
            role=PlayerAccess.Role.PLAYER,
            user__portal_profile__account_type=PortalProfile.AccountType.PLAYER,
        )
        .order_by("created_at")
        .first()
    )
    if existing_access:
        profile = existing_access.user.portal_profile
        changed_profile = not profile.is_active
        changed_user = not profile.user.is_active
        temporary_password = None
        if not existing_access.is_active:
            existing_access.is_active = True
            existing_access.save(update_fields=("is_active",))
        if changed_profile:
            profile.is_active = True
            profile.save(update_fields=("is_active", "updated_at"))
        if not profile.user.has_usable_password():
            temporary_password = generate_temporary_password()
            profile.user.set_password(temporary_password)
            profile.user.is_active = True
            profile.user.save(update_fields=("password", "is_active"))
        elif changed_user:
            profile.user.is_active = True
            profile.user.save(update_fields=("is_active",))
        return profile, temporary_password, False

    if not (player.email or "").strip():
        raise ValueError("Renseignez l’e-mail du joueur avant de créer son compte client.")

    profile, temporary_password = provision_portal_account(
        {
            "account_type": PortalProfile.AccountType.PLAYER,
            "display_name": player.name,
            "email": player.email.strip().lower(),
            "whatsapp_number": player.whatsapp_number or "",
            "preferred_language": "fr",
            "player": player,
            "organization": None,
            "players": (),
        },
        created_by=created_by,
    )
    return profile, temporary_password, True


@transaction.atomic
def issue_reusable_portal_access_link(profile, *, created_by):
    """Issue one reusable, revocable link and retire older links for the account."""
    PortalAccessLink.objects.filter(
        user=profile.user,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    return PortalAccessLink.issue(
        user=profile.user,
        created_by=created_by,
        lifetime=PORTAL_ACCESS_LINK_LIFETIME,
    )


def deliver_portal_credentials(
    profile,
    temporary_password,
    *,
    access_url,
    login_url,
    actor,
    player=None,
):
    recipient_name = profile.display_name
    email = (profile.user.email or "").strip()
    phone_value = profile.whatsapp_number or (
        player.whatsapp_number if player else ""
    )
    phone = normalize_whatsapp_number(phone_value)
    message_parts = [
        f"Bonjour {recipient_name} 👋",
        "Votre espace client MS Football est prêt.",
        f"Ouvrir mon espace : {access_url}",
        (
            "Ce lien est personnel et réutilisable tant que MS Football maintient "
            "votre compte actif."
        ),
    ]
    if temporary_password:
        message_parts.append(
            "Connexion de secours :\n"
            f"{login_url}\n"
            f"E-mail : {email}\n"
            f"Mot de passe temporaire : {temporary_password}"
        )
    message_parts.append(
        "Vous pourrez consulter vos anciennes vidéos et suivre la production en cours."
    )
    message = "\n\n".join(message_parts)

    email_sent = False
    email_error = False
    if email:
        try:
            email_sent = bool(
                send_mail(
                    "Votre espace client MS Football",
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
            )
        except Exception:
            email_error = True
        CommunicationLog.objects.create(
            player=player,
            channel=CommunicationLog.Channel.EMAIL,
            template_key="portal_credentials",
            recipient=email,
            message="Lien sécurisé du portail client préparé par MS Football.",
            state=(
                CommunicationLog.State.SENT
                if email_sent
                else CommunicationLog.State.FAILED
            ),
            actor=actor,
        )

    whatsapp_url = ""
    if phone:
        whatsapp_url = f"https://wa.me/{phone}?text={quote(message, safe='')}"
        CommunicationLog.objects.create(
            player=player,
            channel=CommunicationLog.Channel.WHATSAPP,
            template_key="portal_credentials",
            recipient=phone_value,
            message="Brouillon WhatsApp du lien sécurisé du portail préparé.",
            state=CommunicationLog.State.DRAFT_OPENED,
            actor=actor,
        )

    return PortalCredentialDelivery(
        email_sent=email_sent,
        email_error=email_error,
        whatsapp_url=whatsapp_url,
    )


def update_workflow(video, cleaned_data, *, actor):
    previous_stage = derived_stage(video)
    workflow, _created = VideoWorkflow.objects.get_or_create(
        video=video,
        defaults={
            "stage": previous_stage,
            "progress": STAGE_PROGRESS.get(previous_stage, 0),
            "updated_by": actor,
        },
    )
    for field in ("stage", "priority", "progress", "next_action", "blocked_reason"):
        setattr(workflow, field, cleaned_data[field])
    workflow.updated_by = actor
    workflow.save()

    if previous_stage != workflow.stage:
        VideoActivity.objects.create(
            video=video,
            kind=VideoActivity.Kind.STAGE,
            visibility=VideoActivity.Visibility.CLIENT,
            message=(
                f"Étape passée de « {dict(VideoWorkflow.Stage.choices)[previous_stage]} » "
                f"à « {workflow.get_stage_display()} »."
            ),
            metadata={"from": previous_stage, "to": workflow.stage},
            created_by=actor,
        )
    return workflow


def normalize_whatsapp_number(value):
    return re.sub(r"\D", "", value or "")


def build_video_whatsapp_message(video, template_key):
    player_name = video.player.name
    deadline = video.deadline.strftime("%d/%m/%Y")
    payment = invoice_snapshot(video)
    templates = {
        "welcome": (
            f"Bonjour {player_name} 👋\n\nNous avons bien enregistré ta vidéo "
            f"pour la saison {video.season}. Tu peux maintenant suivre la commande "
            "et transmettre tes éléments depuis ton espace MS Football."
        ),
        "deposit": (
            f"Bonjour {player_name} 👋\n\nTa commande est prête à démarrer. "
            f"Le montant total est de {payment.total:.2f} et l’acompte enregistré "
            f"est de {payment.paid:.2f}. Merci de confirmer l’acompte pour lancer la production."
        ),
        "started": (
            f"Bonjour {player_name} 👋\n\nLe travail sur ta vidéo a commencé. "
            f"La date prévue est le {deadline}. Nous te tiendrons informé depuis ton espace."
        ),
        "review": (
            f"Bonjour {player_name} 👋\n\nUne version de ta vidéo est prête à être vérifiée. "
            "Tu peux la regarder, l’approuver ou indiquer précisément les corrections dans ton espace."
        ),
        "balance": (
            f"Bonjour {player_name} 👋\n\nTa vidéo est terminée. "
            f"Le solde restant est de {payment.balance:.2f}. La livraison finale sera disponible "
            "après confirmation du règlement."
        ),
        "delivery": (
            f"Bonjour {player_name} 👋\n\nTa vidéo finale est disponible dans ton espace "
            "MS Football. Merci pour ta confiance et bonne réussite pour la suite ⚽"
        ),
    }
    if template_key not in templates:
        raise ValueError("Modèle WhatsApp inconnu.")
    return templates[template_key]


def build_video_whatsapp_url(video, template_key, *, actor):
    phone = normalize_whatsapp_number(video.player.whatsapp_number)
    if not phone:
        raise ValueError("Ce joueur n’a pas de numéro WhatsApp.")
    message = build_video_whatsapp_message(video, template_key)
    CommunicationLog.objects.create(
        video=video,
        player=video.player,
        channel=CommunicationLog.Channel.WHATSAPP,
        template_key=template_key,
        recipient=video.player.whatsapp_number or "",
        message=message,
        state=CommunicationLog.State.DRAFT_OPENED,
        actor=actor,
    )
    VideoActivity.objects.create(
        video=video,
        kind=VideoActivity.Kind.MESSAGE,
        visibility=VideoActivity.Visibility.INTERNAL,
        message=f"Brouillon WhatsApp « {template_key} » ouvert.",
        created_by=actor,
    )
    return f"https://wa.me/{phone}?text={quote(message, safe='')}"


def production_brief(videos, *, include_sales=False):
    decorated = [decorate_video(video) for video in videos]
    late = [video for video in decorated if video.is_late]
    blocked = [
        video
        for video in decorated
        if video.production_stage == VideoWorkflow.Stage.BLOCKED
    ]
    awaiting_balance = [
        video
        for video in decorated
        if video.production_stage == VideoWorkflow.Stage.AWAITING_BALANCE
    ]
    review = [
        video
        for video in decorated
        if video.production_stage in {
            VideoWorkflow.Stage.CLIENT_REVIEW,
            VideoWorkflow.Stage.REVISIONS,
        }
    ]
    outstanding = sum(
        (video.payment_snapshot.balance for video in decorated),
        Decimal("0"),
    )
    average_order = (
        sum(
            (video.payment_snapshot.total for video in decorated),
            Decimal("0"),
        )
        / len(decorated)
        if decorated
        else Decimal("0")
    )
    workloads = defaultdict(int)
    for video in decorated:
        if video.production_stage != VideoWorkflow.Stage.DELIVERED:
            workloads[video.editor.user.username] += 1
    editor_workloads = sorted(
        (
            {"editor": editor, "count": count}
            for editor, count in workloads.items()
        ),
        key=lambda item: (-item["count"], item["editor"]),
    )
    open_revisions = RevisionRequest.objects.filter(
        version__video_id__in=[video.pk for video in decorated],
        status__in={
            RevisionRequest.Status.OPEN,
            RevisionRequest.Status.IN_PROGRESS,
        },
    ).count()
    sales_metrics = None
    if include_sales:
        from prospects.models import Prospect

        prospect_total = Prospect.objects.count()
        prospect_converted = Prospect.objects.filter(
            status=Prospect.Status.CONVERTED
        ).count()
        source_performance = list(
            Prospect.objects.values("source")
            .annotate(
                total=Count("id"),
                converted=Count(
                    "id",
                    filter=Q(status=Prospect.Status.CONVERTED),
                ),
            )
            .order_by("-total", "source")[:8]
        )
        sales_metrics = {
            "prospect_total": prospect_total,
            "prospect_converted": prospect_converted,
            "conversion_rate": (
                prospect_converted * 100 / prospect_total if prospect_total else 0
            ),
            "source_performance": source_performance,
        }
    recommendations = []
    if late:
        recommendations.append(
            {
                "severity": "danger",
                "title": f"{len(late)} production(s) en retard",
                "detail": "Vérifier le blocage et prévenir les clients concernés.",
            }
        )
    if awaiting_balance:
        recommendations.append(
            {
                "severity": "warning",
                "title": f"{len(awaiting_balance)} solde(s) à récupérer",
                "detail": f"Montant restant visible : {outstanding:.2f}.",
            }
        )
    if blocked:
        recommendations.append(
            {
                "severity": "danger",
                "title": f"{len(blocked)} production(s) bloquée(s)",
                "detail": "Attribuer une prochaine action et un responsable.",
            }
        )
    if review:
        recommendations.append(
            {
                "severity": "info",
                "title": f"{len(review)} validation(s) ou correction(s)",
                "detail": "Relancer les validations et traiter les demandes ouvertes.",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "severity": "success",
                "title": "Aucune urgence détectée",
                "detail": "Le flux de production ne présente pas de blocage prioritaire.",
            }
        )
    return {
        "videos": decorated,
        "late": late,
        "blocked": blocked,
        "awaiting_balance": awaiting_balance,
        "review": review,
        "outstanding": outstanding,
        "average_order": average_order,
        "open_revisions": open_revisions,
        "editor_workloads": editor_workloads,
        "sales_metrics": sales_metrics,
        "recommendations": recommendations,
    }
