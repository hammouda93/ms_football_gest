from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from gestion_joueurs.models import Player, Video, VideoEditor
from gestion_joueurs.video_status_whatsapp import (
    PAYMENT_MODE_CHOICES,
    build_status_notification_context,
    build_whatsapp_url,
    ensure_delivery_link_in_message,
)

from .decorators import portal_admin_required, portal_required, production_required
from .forms import (
    AgentPlayerRequestForm,
    MediaSubmissionForm,
    OrganizationForm,
    OrganizationPlayerForm,
    PaymentRequestForm,
    PortalAccountForm,
    PortalLoginForm,
    ProductionVideoStatusForm,
    RevisionRequestForm,
    RevisionResolutionForm,
    VideoActivityForm,
    VideoVersionForm,
    VideoWorkflowForm,
)
from .models import (
    AgentPlayerRequest,
    CommunicationLog,
    Organization,
    OrganizationPlayer,
    PaymentRequest,
    PortalAccessLink,
    PortalProfile,
    RevisionRequest,
    VideoActivity,
    VideoVersion,
    VideoWorkflow,
)
from .services import (
    STAGE_NEXT_ACTION,
    STAGE_PROGRESS,
    accessible_players_for,
    accessible_videos_for,
    build_video_whatsapp_url,
    client_video_timeline,
    decorate_client_video,
    decorate_video,
    deliver_portal_credentials,
    editable_videos_for,
    invoice_snapshot,
    issue_reusable_portal_access_link,
    portal_access_states_for_players,
    provision_portal_account,
    production_brief,
    production_queryset_for,
    update_workflow,
)


WHATSAPP_ACTIONS = (
    ("welcome", "Bienvenue / accès au portail"),
    ("deposit", "Demander l’acompte"),
    ("started", "Confirmer le démarrage"),
    ("review", "Demander la validation"),
    ("balance", "Demander le solde"),
    ("delivery", "Confirmer la livraison"),
)


def _portal_user_from_login_data(request):
    data = request.POST.copy()
    supplied = data.get("username", "").strip()
    if "@" in supplied:
        profile = PortalProfile.objects.select_related("user").filter(
            user__email__iexact=supplied,
            is_active=True,
        ).first()
        if profile:
            data["username"] = profile.user.username
    return data


@never_cache
@ensure_csrf_cookie
def portal_login(request):
    if request.user.is_authenticated:
        try:
            if request.user.portal_profile.is_active:
                return redirect("portal:dashboard")
        except Exception:
            pass

    data = _portal_user_from_login_data(request) if request.method == "POST" else None
    form = PortalLoginForm(request=request, data=data)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        try:
            profile = user.portal_profile
        except Exception:
            profile = None
        if not profile or not profile.is_active:
            form.add_error(None, "Ce compte ne possède pas d’accès au portail.")
        else:
            login(request, user)
            return redirect("portal:dashboard")
    return render(request, "client_portal/login.html", {"form": form})


@login_required(login_url="portal:login")
@require_POST
def portal_logout(request):
    logout(request)
    return redirect("portal:login")


@never_cache
@portal_required
def portal_password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Votre mot de passe a été modifié.")
        return redirect("portal:dashboard")
    return render(
        request,
        "client_portal/password_change.html",
        {"form": form},
    )


@never_cache
def portal_magic_access(request, token):
    token_hash = PortalAccessLink.hash_token(token)
    access_link = PortalAccessLink.objects.select_related(
        "user",
        "user__portal_profile",
    ).filter(token_hash=token_hash).first()
    if not access_link or not access_link.is_usable:
        return render(
            request,
            "client_portal/access_invalid.html",
            status=410,
        )

    login(
        request,
        access_link.user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    access_link.used_at = timezone.now()
    access_link.save(update_fields=("used_at",))
    return redirect("portal:dashboard")


def _apply_production_filters(request, queryset):
    query = request.GET.get("q", "").strip()
    editor_id = request.GET.get("editor", "").strip()
    if query:
        queryset = queryset.filter(
            Q(player__name__icontains=query)
            | Q(player__club__icontains=query)
            | Q(season__icontains=query)
        )
    if request.user.is_superuser and editor_id.isdigit():
        queryset = queryset.filter(editor_id=int(editor_id))
    return queryset, query, editor_id


@production_required
def production_board(request):
    queryset, query, editor_id = _apply_production_filters(
        request,
        production_queryset_for(request.user),
    )
    videos = [decorate_video(video) for video in queryset.order_by("deadline", "id")]
    selected_stage = request.GET.get("stage", "").strip()
    valid_stages = {value for value, _label in VideoWorkflow.Stage.choices}
    if selected_stage in valid_stages:
        videos = [video for video in videos if video.production_stage == selected_stage]
    else:
        selected_stage = ""

    columns = []
    for stage, label in VideoWorkflow.Stage.choices:
        stage_videos = [video for video in videos if video.production_stage == stage]
        columns.append(
            {
                "key": stage,
                "label": label,
                "videos": stage_videos,
                "count": len(stage_videos),
            }
        )

    metrics = {
        "total": len(videos),
        "late": sum(video.is_late for video in videos),
        "blocked": sum(
            video.production_stage == VideoWorkflow.Stage.BLOCKED for video in videos
        ),
        "review": sum(
            video.production_stage
            in {VideoWorkflow.Stage.CLIENT_REVIEW, VideoWorkflow.Stage.REVISIONS}
            for video in videos
        ),
        "outstanding": sum(
            (video.payment_snapshot.balance for video in videos),
            Decimal("0"),
        ),
    }
    return render(
        request,
        "client_portal/production_board.html",
        {
            "columns": columns,
            "metrics": metrics,
            "query": query,
            "selected_stage": selected_stage,
            "selected_editor": editor_id,
            "stage_choices": VideoWorkflow.Stage.choices,
            "editors": VideoEditor.objects.select_related("user").order_by(
                "user__username"
            ),
        },
    )


def _staff_video_or_404(user, video_id):
    return get_object_or_404(production_queryset_for(user), pk=video_id)


@production_required
def production_video_detail(request, video_id):
    video = decorate_video(_staff_video_or_404(request.user, video_id))
    try:
        workflow = video.production_workflow
    except VideoWorkflow.DoesNotExist:
        workflow = None
    workflow_initial = {
        "stage": video.production_stage,
        "priority": video.production_priority,
        "progress": video.production_progress,
        "next_action": video.production_next_action,
        "blocked_reason": video.production_blocked_reason,
    }
    revisions = RevisionRequest.objects.filter(
        version__video=video
    ).select_related("version", "requested_by", "resolved_by")
    portal_state = portal_access_states_for_players((video.player_id,)).get(
        video.player_id,
        "none",
    )
    context = {
        "video": video,
        "client_portal_state": portal_state,
        "status_form": ProductionVideoStatusForm(
            user=request.user,
            video=video,
        ),
        "workflow_form": VideoWorkflowForm(
            instance=workflow,
            initial=workflow_initial,
        ),
        "activity_form": VideoActivityForm(),
        "version_form": VideoVersionForm(),
        "payment_request_form": PaymentRequestForm(
            initial={"amount": video.payment_snapshot.balance}
        ),
        "versions": video.portal_versions.select_related(
            "uploaded_by", "approved_by"
        ).prefetch_related("revision_requests"),
        "revisions": revisions,
        "media_submissions": video.media_submissions.select_related(
            "submitted_by"
        ),
        "activities": video.portal_activities.select_related("created_by")[:50],
        "payment_requests": video.portal_payment_requests.all(),
        "communications": video.communication_logs.select_related("actor")[:20],
        "whatsapp_actions": WHATSAPP_ACTIONS,
    }
    context.update(build_status_notification_context(video))
    return render(
        request,
        "client_portal/production_video_detail.html",
        context,
    )


@production_required
@require_POST
def production_video_status_update(request, video_id):
    video = _staff_video_or_404(request.user, video_id)
    form = ProductionVideoStatusForm(
        request.POST,
        user=request.user,
        video=video,
    )
    if not form.is_valid():
        messages.error(
            request,
            "L’état n’a pas été modifié. Vérifiez les informations proposées.",
        )
        return redirect("portal:production_video", video_id=video.pk)

    previous_status = video.status
    new_status = form.cleaned_data["status"]
    update_fields = []
    if previous_status != new_status:
        video.status = new_status
        update_fields.append("status")

    if new_status == Video.StatusChoices.DELIVERED:
        submitted_link = (form.cleaned_data.get("video_link") or "").strip()
        if submitted_link != (video.video_link or ""):
            video.video_link = submitted_link
            update_fields.append("video_link")

    if update_fields:
        video.save(update_fields=tuple(update_fields))
        messages.success(request, "L’état officiel de la vidéo a été mis à jour.")
    else:
        messages.info(request, "Aucun changement d’état n’était nécessaire.")

    status_changed = previous_status != new_status
    if status_changed and request.POST.get("notification_action") == "whatsapp":
        payment_mode = request.POST.get("payment_message_mode", "auto")
        valid_payment_modes = {value for value, _label in PAYMENT_MODE_CHOICES}
        if payment_mode not in valid_payment_modes:
            payment_mode = "auto"

        notification_context = build_status_notification_context(video)
        whatsapp_message = request.POST.get("whatsapp_message", "").strip()
        if not whatsapp_message:
            whatsapp_message = notification_context["status_whatsapp_messages"][
                video.status
            ][payment_mode]
        whatsapp_message = ensure_delivery_link_in_message(
            whatsapp_message,
            video,
            video.status,
        )
        whatsapp_url = build_whatsapp_url(
            video.player.whatsapp_number,
            whatsapp_message[:4000],
        )
        if whatsapp_url:
            CommunicationLog.objects.create(
                video=video,
                player=video.player,
                channel=CommunicationLog.Channel.WHATSAPP,
                template_key=f"status_{video.status}",
                recipient=video.player.whatsapp_number or "",
                message=whatsapp_message[:4000],
                state=CommunicationLog.State.DRAFT_OPENED,
                actor=request.user,
            )
            return redirect(whatsapp_url)
        messages.warning(
            request,
            "L’état est enregistré, mais aucun numéro WhatsApp n’est renseigné.",
        )

    return redirect("portal:production_video", video_id=video.pk)


@production_required
@require_POST
def production_workflow_update(request, video_id):
    video = _staff_video_or_404(request.user, video_id)
    try:
        workflow = video.production_workflow
    except VideoWorkflow.DoesNotExist:
        workflow = None
    form = VideoWorkflowForm(request.POST, instance=workflow)
    if form.is_valid():
        update_workflow(video, form.cleaned_data, actor=request.user)
        messages.success(request, "Le suivi de production a été mis à jour.")
    else:
        messages.error(request, "Vérifiez les informations du suivi de production.")
    return redirect("portal:production_video", video_id=video.pk)


@production_required
@require_POST
def production_activity_add(request, video_id):
    video = _staff_video_or_404(request.user, video_id)
    form = VideoActivityForm(request.POST)
    if form.is_valid():
        activity = form.save(commit=False)
        activity.video = video
        activity.kind = VideoActivity.Kind.NOTE
        activity.created_by = request.user
        activity.save()
        messages.success(request, "La note a été ajoutée au dossier.")
    else:
        messages.error(request, "La note n’a pas pu être ajoutée.")
    return redirect("portal:production_video", video_id=video.pk)


@production_required
@require_POST
def production_version_add(request, video_id):
    video = _staff_video_or_404(request.user, video_id)
    form = VideoVersionForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            latest = (
                VideoVersion.objects.select_for_update()
                .filter(video=video)
                .aggregate(number=Max("version_number"))["number"]
                or 0
            )
            VideoVersion.objects.filter(
                video=video,
                status=VideoVersion.Status.PENDING,
            ).update(status=VideoVersion.Status.REPLACED)
            version = form.save(commit=False)
            version.video = video
            version.version_number = latest + 1
            version.uploaded_by = request.user
            version.save()
            VideoActivity.objects.create(
                video=video,
                kind=VideoActivity.Kind.VERSION,
                visibility=VideoActivity.Visibility.CLIENT,
                message=f"La version {version.version_number} est disponible pour validation.",
                created_by=request.user,
            )
        messages.success(request, "La nouvelle version est disponible sur le portail.")
    else:
        messages.error(request, "Vérifiez le lien et les informations de la version.")
    return redirect("portal:production_video", video_id=video.pk)


@production_required
@require_POST
def production_revision_resolve(request, revision_id):
    revision = get_object_or_404(
        RevisionRequest.objects.select_related("version__video"),
        pk=revision_id,
        version__video__in=production_queryset_for(request.user),
    )
    form = RevisionResolutionForm(request.POST)
    if form.is_valid():
        revision.status = form.cleaned_data["status"]
        revision.staff_response = form.cleaned_data["staff_response"]
        if revision.status in {
            RevisionRequest.Status.RESOLVED,
            RevisionRequest.Status.REJECTED,
        }:
            revision.resolved_at = timezone.now()
            revision.resolved_by = request.user
        else:
            revision.resolved_at = None
            revision.resolved_by = None
        revision.save()
        VideoActivity.objects.create(
            video=revision.version.video,
            kind=VideoActivity.Kind.REVIEW,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"Correction mise à jour : {revision.get_status_display()}.",
            created_by=request.user,
        )
        messages.success(request, "La demande de correction a été mise à jour.")
    else:
        messages.error(request, "La correction n’a pas pu être mise à jour.")
    return redirect(
        "portal:production_video",
        video_id=revision.version.video_id,
    )


@production_required
@require_POST
def production_payment_request_add(request, video_id):
    video = _staff_video_or_404(request.user, video_id)
    form = PaymentRequestForm(request.POST)
    if form.is_valid():
        payment_request = form.save(commit=False)
        payment_request.video = video
        payment_request.created_by = request.user
        payment_request.save()
        VideoActivity.objects.create(
            video=video,
            kind=VideoActivity.Kind.PAYMENT,
            visibility=VideoActivity.Visibility.CLIENT,
            message=(
                f"Une demande de paiement « {payment_request.label} » de "
                f"{payment_request.amount:.2f} est disponible."
            ),
            created_by=request.user,
        )
        messages.success(request, "La demande de paiement a été créée.")
    else:
        messages.error(request, "Vérifiez les informations de paiement.")
    return redirect("portal:production_video", video_id=video.pk)


@production_required
@require_POST
def production_whatsapp(request, video_id, action):
    video = _staff_video_or_404(request.user, video_id)
    try:
        target = build_video_whatsapp_url(video, action, actor=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("portal:production_video", video_id=video.pk)
    return redirect(target)


@production_required
def operations_brief(request):
    brief = production_brief(
        list(production_queryset_for(request.user).order_by("deadline", "id")),
        include_sales=request.user.is_superuser,
    )
    return render(request, "client_portal/operations_brief.html", {"brief": brief})


@portal_admin_required
def portal_management(request):
    profiles = list(
        PortalProfile.objects.select_related("user").prefetch_related(
            "user__portal_player_accesses__player",
            "user__portal_memberships__organization",
        )
    )
    return render(
        request,
        "client_portal/management.html",
        {
            "organizations": Organization.objects.annotate(
                active_player_count=Count(
                    "player_links",
                    filter=Q(player_links__is_active=True),
                    distinct=True,
                ),
                access_count=Count(
                    "memberships",
                    filter=Q(memberships__is_active=True),
                    distinct=True,
                ),
            ).prefetch_related("memberships", "player_links"),
            "profiles": profiles,
            "active_profile_count": sum(
                profile.access_enabled for profile in profiles
            ),
            "agent_requests": AgentPlayerRequest.objects.select_related(
                "organization", "requested_by", "linked_player"
            )[:50],
            "all_players": Player.objects.order_by("name", "club"),
        },
    )


@portal_admin_required
def organization_create(request):
    form = OrganizationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        organization = form.save(commit=False)
        organization.created_by = request.user
        organization.save()
        messages.success(request, "L’organisation a été créée.")
        return redirect("portal:organization_detail", pk=organization.pk)
    return render(
        request,
        "client_portal/organization_form.html",
        {"form": form},
    )


@portal_admin_required
def organization_detail(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    player_links = organization.player_links.select_related("player", "added_by")
    return render(
        request,
        "client_portal/organization_detail.html",
        {
            "organization": organization,
            "player_form": OrganizationPlayerForm(organization=organization),
            "player_links": player_links.filter(is_active=True),
            "former_player_links": player_links.filter(is_active=False),
            "memberships": organization.memberships.select_related("user", "user__portal_profile"),
            "agent_requests": organization.player_requests.select_related(
                "requested_by", "linked_player"
            ),
            "all_players": Player.objects.order_by("name", "club"),
        },
    )


@portal_admin_required
@require_POST
def organization_player_add(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    form = OrganizationPlayerForm(request.POST, organization=organization)
    if form.is_valid():
        link, created = OrganizationPlayer.objects.update_or_create(
            organization=organization,
            player=form.cleaned_data["player"],
            defaults={
                "label": form.cleaned_data["label"],
                "is_active": True,
                "ended_at": None,
                "added_by": request.user,
            },
        )
        messages.success(
            request,
            "Le joueur est maintenant visible dans l’espace de l’organisation."
            if created
            else "L’accès du joueur a été réactivé.",
        )
    else:
        messages.error(request, "Sélectionnez un joueur valide.")
    return redirect("portal:organization_detail", pk=organization.pk)


@portal_admin_required
@require_POST
def organization_player_remove(request, pk, link_id):
    organization = get_object_or_404(Organization, pk=pk)
    link = get_object_or_404(
        OrganizationPlayer,
        pk=link_id,
        organization=organization,
    )
    player_name = link.player.name
    link.is_active = False
    link.ended_at = timezone.now()
    link.save(update_fields=("is_active", "ended_at"))
    messages.success(
        request,
        f"La relation avec {player_name} a été clôturée. Sa fiche et son historique restent intacts.",
    )
    return redirect("portal:organization_detail", pk=organization.pk)


def _account_form_context(form):
    return {
        "form": form,
        "player_options": list(
            Player.objects.order_by("name", "club").values(
                "id", "name", "club", "email", "whatsapp_number"
            )
        ),
        "organization_options": list(
            Organization.objects.filter(is_active=True)
            .order_by("name")
            .values("id", "name", "contact_name", "email", "whatsapp_number")
        ),
    }


def _account_player(profile):
    access = (
        profile.user.portal_player_accesses.select_related("player")
        .filter(role="player")
        .first()
    )
    return access.player if access else None


def _render_account_credentials(request, profile, temporary_password=None, *, player=None):
    access_link, raw_token = issue_reusable_portal_access_link(
        profile,
        created_by=request.user,
    )
    access_url = request.build_absolute_uri(
        reverse("portal:magic_access", args=(raw_token,))
    )
    login_url = request.build_absolute_uri(reverse("portal:login"))
    delivery = deliver_portal_credentials(
        profile,
        temporary_password,
        access_url=access_url,
        login_url=login_url,
        actor=request.user,
        player=player or _account_player(profile),
    )
    return render(
        request,
        "client_portal/access_link_created.html",
        {
            "profile": profile,
            "access_link": access_link,
            "access_url": access_url,
            "login_url": login_url,
            "login_email": profile.user.email,
            "temporary_password": temporary_password,
            "delivery": delivery,
        },
    )


@portal_admin_required
def portal_account_create(request):
    form = PortalAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        profile, temporary_password = provision_portal_account(
            form.cleaned_data,
            created_by=request.user,
        )
        return _render_account_credentials(
            request,
            profile,
            temporary_password,
            player=form.cleaned_data.get("player"),
        )
    return render(
        request,
        "client_portal/account_form.html",
        _account_form_context(form),
    )


@portal_admin_required
@require_POST
def portal_access_link_generate(request, profile_id):
    profile = get_object_or_404(
        PortalProfile.objects.select_related("user"),
        pk=profile_id,
    )
    if not profile.access_enabled:
        messages.error(
            request,
            "Réactivez d’abord le compte avant de renouveler son lien sécurisé.",
        )
        return redirect("portal:management")
    return _render_account_credentials(request, profile)


@portal_admin_required
@require_POST
def portal_account_toggle(request, profile_id):
    profile = get_object_or_404(
        PortalProfile.objects.select_related("user"),
        pk=profile_id,
    )
    action = request.POST.get("action", "")
    if action not in {"activate", "deactivate"}:
        messages.error(request, "Action de compte invalide.")
        return redirect("portal:management")
    activate = action == "activate"
    with transaction.atomic():
        profile.is_active = activate
        profile.save(update_fields=("is_active", "updated_at"))
        profile.user.is_active = activate
        profile.user.save(update_fields=("is_active",))
    messages.success(
        request,
        f"Le compte de {profile.display_name} est maintenant "
        f"{'actif' if activate else 'désactivé'}.",
    )
    return redirect("portal:management")


@portal_admin_required
@require_POST
def agent_player_request_review(request, request_id):
    player_request = get_object_or_404(AgentPlayerRequest, pk=request_id)
    decision = request.POST.get("decision", "")
    if decision == "reject":
        player_request.status = AgentPlayerRequest.Status.REJECTED
        player_request.reviewed_by = request.user
        player_request.save(update_fields=("status", "reviewed_by", "updated_at"))
        messages.success(request, "La demande a été refusée sans modifier les joueurs.")
    elif decision == "link":
        player_id = request.POST.get("player_id", "")
        if not player_id.isdigit():
            messages.error(request, "Sélectionnez le joueur existant à associer.")
            return redirect(
                "portal:organization_detail",
                pk=player_request.organization_id,
            )
        player = get_object_or_404(Player, pk=int(player_id))
        OrganizationPlayer.objects.update_or_create(
            organization=player_request.organization,
            player=player,
            defaults={
                "is_active": True,
                "ended_at": None,
                "added_by": request.user,
            },
        )
        player_request.status = AgentPlayerRequest.Status.LINKED
        player_request.linked_player = player
        player_request.reviewed_by = request.user
        player_request.save(
            update_fields=("status", "linked_player", "reviewed_by", "updated_at")
        )
        messages.success(request, "Le joueur existant a été associé à l’organisation.")
    else:
        messages.error(request, "Décision invalide.")
    return redirect(
        "portal:organization_detail",
        pk=player_request.organization_id,
    )


@never_cache
@portal_required
def portal_dashboard(request):
    players = list(accessible_players_for(request.user).order_by("name", "club"))
    videos = [
        decorate_client_video(video)
        for video in accessible_videos_for(request.user).order_by("-video_creation_date")
    ]
    current_videos = [
        video
        for video in videos
        if video.production_stage != VideoWorkflow.Stage.DELIVERED
    ]
    archived_videos = [
        video
        for video in videos
        if video.production_stage == VideoWorkflow.Stage.DELIVERED
    ]
    organizations = Organization.objects.filter(
        memberships__user=request.user,
        memberships__is_active=True,
        is_active=True,
    ).distinct()
    agent_request_form = AgentPlayerRequestForm(user=request.user)
    player_videos = defaultdict(list)
    for video in videos:
        player_videos[video.player_id].append(video)
    for player in players:
        related_videos = player_videos.get(player.pk, [])
        player.portal_active_count = sum(
            video.production_stage != VideoWorkflow.Stage.DELIVERED
            for video in related_videos
        )
        player.portal_review_count = sum(
            video.client_review_count for video in related_videos
        )
        player.portal_action_count = sum(
            video.client_action_count for video in related_videos
        )
        player.portal_balance = sum(
            (video.payment_snapshot.balance for video in related_videos),
            Decimal("0"),
        )
    from sportsbase_data.services import active_subscriptions

    performance_subscriptions = list(
        active_subscriptions()
        .filter(player_id__in=[player.pk for player in players])
        .select_related("player")
    )
    performance_by_player = {
        subscription.player_id: subscription
        for subscription in performance_subscriptions
    }
    for player in players:
        player.portal_performance_subscription = performance_by_player.get(player.pk)
    return render(
        request,
        "client_portal/dashboard.html",
        {
            "players": players,
            "videos": videos,
            "current_videos": current_videos,
            "archived_videos": archived_videos,
            "organizations": organizations,
            "agent_request_form": agent_request_form,
            "can_request_players": agent_request_form.fields[
                "organization"
            ].queryset.exists(),
            "active_count": len(current_videos),
            "review_count": sum(
                video.client_review_count for video in current_videos
            ),
            "required_action_count": sum(
                video.client_action_count for video in current_videos
            ),
            "balance": sum(
                (video.payment_snapshot.balance for video in videos),
                Decimal("0"),
            ),
            "performance_subscriptions": performance_subscriptions,
        },
    )


@never_cache
@portal_required
def portal_player_detail(request, player_id):
    player = get_object_or_404(accessible_players_for(request.user), pk=player_id)
    videos = [
        decorate_client_video(video)
        for video in accessible_videos_for(request.user)
        .filter(player=player)
        .order_by("-video_creation_date")
    ]
    current_videos = [
        video
        for video in videos
        if video.production_stage != VideoWorkflow.Stage.DELIVERED
    ]
    archived_videos = [
        video
        for video in videos
        if video.production_stage == VideoWorkflow.Stage.DELIVERED
    ]
    from sportsbase_data.services import active_subscriptions

    performance_subscription = active_subscriptions().filter(player=player).first()
    return render(
        request,
        "client_portal/player_detail.html",
        {
            "player": player,
            "videos": videos,
            "current_videos": current_videos,
            "archived_videos": archived_videos,
            "performance_subscription": performance_subscription,
        },
    )


@never_cache
@portal_required
def portal_video_detail(request, video_id):
    video = decorate_video(
        get_object_or_404(accessible_videos_for(request.user), pk=video_id)
    )
    versions = video.portal_versions.prefetch_related("revision_requests")
    activities = list(
        video.portal_activities.filter(
            visibility=VideoActivity.Visibility.CLIENT
        ).select_related("created_by")[:30]
    )
    timeline_events = client_video_timeline(video, activities)
    return render(
        request,
        "client_portal/video_detail.html",
        {
            "video": video,
            "media_form": MediaSubmissionForm(),
            "revision_form": RevisionRequestForm(),
            "versions": versions,
            "media_submissions": video.media_submissions.select_related("submitted_by"),
            "activities": activities,
            "timeline_events": timeline_events,
            "payment_requests": video.portal_payment_requests.exclude(
                status__in={PaymentRequest.Status.CANCELLED, PaymentRequest.Status.EXPIRED}
            ),
            "can_edit_video": editable_videos_for(request.user)
            .filter(pk=video.pk)
            .exists(),
        },
    )


@portal_required
@require_POST
def portal_media_submit(request, video_id):
    video = get_object_or_404(editable_videos_for(request.user), pk=video_id)
    form = MediaSubmissionForm(request.POST)
    if form.is_valid():
        submission = form.save(commit=False)
        submission.video = video
        submission.submitted_by = request.user
        submission.save()
        VideoActivity.objects.create(
            video=video,
            kind=VideoActivity.Kind.MEDIA,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"Nouvel élément transmis : {submission.title}.",
            created_by=request.user,
        )
        messages.success(request, "Le lien a été transmis à l’équipe MS Football.")
    else:
        messages.error(request, "Vérifiez le lien et les informations saisies.")
    return redirect("portal:video", video_id=video.pk)


@portal_required
@require_POST
def portal_revision_request(request, version_id):
    version = get_object_or_404(
        VideoVersion.objects.select_related("video"),
        pk=version_id,
        video__in=editable_videos_for(request.user),
    )
    form = RevisionRequestForm(request.POST)
    if form.is_valid():
        revision = RevisionRequest.objects.create(
            version=version,
            requested_by=request.user,
            timecode_seconds=form.cleaned_data["timecode"],
            comment=form.cleaned_data["comment"],
        )
        if version.status != VideoVersion.Status.APPROVED:
            version.status = VideoVersion.Status.CHANGES_REQUESTED
            version.save(update_fields=("status",))
        workflow, _created = VideoWorkflow.objects.get_or_create(
            video=version.video,
            defaults={
                "stage": VideoWorkflow.Stage.REVISIONS,
                "progress": STAGE_PROGRESS[VideoWorkflow.Stage.REVISIONS],
                "next_action": STAGE_NEXT_ACTION[VideoWorkflow.Stage.REVISIONS],
                "updated_by": request.user,
            },
        )
        if workflow.stage != VideoWorkflow.Stage.REVISIONS:
            workflow.stage = VideoWorkflow.Stage.REVISIONS
            workflow.progress = STAGE_PROGRESS[VideoWorkflow.Stage.REVISIONS]
            workflow.next_action = STAGE_NEXT_ACTION[VideoWorkflow.Stage.REVISIONS]
            workflow.updated_by = request.user
            workflow.save()
        VideoActivity.objects.create(
            video=version.video,
            kind=VideoActivity.Kind.REVIEW,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"Correction demandée sur la version {version.version_number}.",
            metadata={"revision_id": revision.pk},
            created_by=request.user,
        )
        messages.success(request, "La correction a été envoyée à l’équipe.")
    else:
        messages.error(request, "La correction n’a pas pu être enregistrée.")
    return redirect("portal:video", video_id=version.video_id)


@portal_required
@require_POST
def portal_version_approve(request, version_id):
    version = get_object_or_404(
        VideoVersion.objects.select_related("video"),
        pk=version_id,
        video__in=editable_videos_for(request.user),
    )
    with transaction.atomic():
        version.status = VideoVersion.Status.APPROVED
        version.approved_by = request.user
        version.approved_at = timezone.now()
        version.save(update_fields=("status", "approved_by", "approved_at"))
        payment = invoice_snapshot(version.video)
        target_stage = (
            VideoWorkflow.Stage.AWAITING_BALANCE
            if payment.balance > 0
            else VideoWorkflow.Stage.READY_DELIVERY
        )
        workflow, _created = VideoWorkflow.objects.get_or_create(
            video=version.video,
            defaults={
                "stage": target_stage,
                "progress": STAGE_PROGRESS[target_stage],
                "next_action": STAGE_NEXT_ACTION[target_stage],
                "updated_by": request.user,
            },
        )
        if workflow.stage != target_stage:
            workflow.stage = target_stage
            workflow.progress = STAGE_PROGRESS[target_stage]
            workflow.next_action = STAGE_NEXT_ACTION[target_stage]
            workflow.updated_by = request.user
            workflow.save()
        VideoActivity.objects.create(
            video=version.video,
            kind=VideoActivity.Kind.REVIEW,
            visibility=VideoActivity.Visibility.CLIENT,
            message=f"Version {version.version_number} approuvée.",
            created_by=request.user,
        )
    messages.success(request, "Merci, la version a été approuvée.")
    return redirect("portal:video", video_id=version.video_id)


@portal_required
@require_POST
def portal_payment_open(request, payment_request_id):
    payment_request = get_object_or_404(
        PaymentRequest.objects.select_related("video"),
        pk=payment_request_id,
        video__in=accessible_videos_for(request.user),
    )
    if not payment_request.payment_url:
        messages.info(
            request,
            "Le lien de paiement n’est pas encore disponible. Contactez MS Football.",
        )
        return redirect("portal:video", video_id=payment_request.video_id)
    if payment_request.status == PaymentRequest.Status.PENDING:
        payment_request.status = PaymentRequest.Status.OPENED
        payment_request.save(update_fields=("status", "updated_at"))
    return redirect(payment_request.payment_url)


@portal_required
@require_POST
def portal_agent_player_request(request):
    form = AgentPlayerRequestForm(request.POST, user=request.user)
    if form.is_valid():
        player_request = form.save(commit=False)
        player_request.requested_by = request.user
        player_request.save()
        messages.success(
            request,
            "La demande a été transmise. Aucun joueur n’est créé automatiquement.",
        )
    else:
        messages.error(request, "Vérifiez les informations de la demande.")
    return redirect("portal:dashboard")


def portal_manifest(request):
    return JsonResponse(
        {
            "name": "MS Football — Espace client",
            "short_name": "MS Football",
            "start_url": reverse("portal:dashboard"),
            "scope": "/portal/",
            "display": "standalone",
            "background_color": "#071423",
            "theme_color": "#0d6efd",
            "icons": [
                {
                    "src": static("client_portal/ms-football-app.svg"),
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        },
        content_type="application/manifest+json",
    )


def portal_service_worker(request):
    response = HttpResponse(
        """
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request));
});
""".strip(),
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/portal/"
    response["Cache-Control"] = "no-cache"
    return response
