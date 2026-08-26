import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from client_portal.decorators import (
    portal_admin_required,
    portal_required,
    production_required,
)
from client_portal.models import PlayerAccess, PortalProfile
from client_portal.services import accessible_players_for

from .forms import PerformanceReportForm, SportsBaseSubscriptionForm
from .models import (
    PerformanceReport,
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
    SportsBaseYouTubeUpload,
)
from .reports import (
    generate_reports_for_subscription,
    render_report_pdf,
    send_ready_delivery_notification,
)
from .services import (
    active_subscriptions,
    apply_sync_result,
    apply_youtube_upload_result,
    claim_next_job,
    claim_next_youtube_upload,
    fail_sync_job,
    queue_sync,
    retry_youtube_upload,
)


MATCH_METRIC_PAIRS = (
    ("Passes", "Passes accurate, %", "fa-share-nodes"),
    ("Challenges", "Challenges won, %", "fa-people-arrows-left-right"),
    ("Shots", "Shots on target, %", "fa-bullseye"),
    ("Crosses", "Crosses accurate, %", "fa-arrows-left-right-to-line"),
    ("Tackles", "Tackles successful, %", "fa-shield-halved"),
    ("Dribbles", "Dribbles successful, %", "fa-person-running"),
    (
        "Aerial challenges",
        "Aerial challenges won, %",
        "fa-arrow-up-wide-short",
    ),
)


def _normalized_statistics(*collections):
    """Merge scraped dictionaries while keeping one value per statistic."""
    merged = {}
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        for name, value in collection.items():
            key = str(name).strip().casefold()
            if key:
                merged[key] = {"name": str(name).strip(), "value": value}
    return merged


def _percentage_for_chart(value):
    """Return a safe 0-100 value for portal-only visual indicators."""
    if value is None or isinstance(value, bool):
        return None
    cleaned = str(value).strip().replace("%", "").replace(",", ".")
    if not cleaned or cleaned in {"-", "–", "—"}:
        return None
    try:
        percentage = float(cleaned)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, percentage)), 1)


def _build_match_analysis(stats):
    if stats is None:
        return [], []

    values = _normalized_statistics(
        stats.detailed_statistics,
        stats.summary_statistics,
    )
    rates = _normalized_statistics(
        stats.detailed_statistics,
        stats.success_rates,
    )
    consumed = {"index", "minutes played"}
    pairs = []

    for metric_name, rate_name, icon in MATCH_METRIC_PAIRS:
        metric_key = metric_name.casefold()
        rate_key = rate_name.casefold()
        metric = values.get(metric_key)
        rate = rates.get(rate_key)
        if metric is None and rate is None:
            continue
        consumed.update((metric_key, rate_key))
        rate_value = rate.get("value") if rate else None
        chart_percent = _percentage_for_chart(rate_value)
        pairs.append(
            {
                "name": metric_name,
                "value": metric.get("value") if metric else None,
                "rate_name": rate_name,
                "rate_value": rate_value,
                "chart_percent": chart_percent or 0,
                "has_rate": chart_percent is not None,
                "icon": icon,
            }
        )

    other = []
    for key, item in values.items():
        if key not in consumed:
            other.append(item)
            consumed.add(key)
    for key, item in rates.items():
        if key not in consumed:
            other.append(item)
            consumed.add(key)
    return pairs, other


def _build_season_analysis(snapshot):
    """Pair season action volumes with success rates and per-match rhythm."""
    if snapshot is None:
        return [], [], []

    totals = _normalized_statistics(snapshot.season_statistics)
    averages = _normalized_statistics(snapshot.average_statistics)
    consumed = {"index", "matches played", "minutes played"}
    pairs = []

    for metric_name, rate_name, icon in MATCH_METRIC_PAIRS:
        metric_key = metric_name.casefold()
        rate_key = rate_name.casefold()
        metric = totals.get(metric_key)
        rate = totals.get(rate_key) or averages.get(rate_key)
        average = averages.get(metric_key)
        if metric is None and rate is None and average is None:
            continue
        consumed.update((metric_key, rate_key))
        rate_value = rate.get("value") if rate else None
        chart_percent = _percentage_for_chart(rate_value)
        pairs.append(
            {
                "name": metric_name,
                "value": metric.get("value") if metric else None,
                "average_value": average.get("value") if average else None,
                "rate_name": rate_name,
                "rate_value": rate_value,
                "chart_percent": chart_percent or 0,
                "has_rate": chart_percent is not None,
                "icon": icon,
            }
        )

    season_other = [
        item for key, item in totals.items() if key not in consumed
    ]
    average_other = [
        item for key, item in averages.items() if key not in consumed
    ]
    return pairs, season_other, average_other


def _portal_subscriptions_for(user):
    return active_subscriptions().filter(player__in=accessible_players_for(user))


def _portal_subscription_or_404(user, player_id):
    return get_object_or_404(
        _portal_subscriptions_for(user).select_related("player"),
        player_id=player_id,
    )


def _sync_direct_portal_language(subscription):
    """Keep both internal language selectors coherent for direct player accounts."""
    profile = (
        PortalProfile.objects.filter(
            user__portal_player_accesses__player=subscription.player,
            user__portal_player_accesses__role=PlayerAccess.Role.PLAYER,
            account_type=PortalProfile.AccountType.PLAYER,
        )
        .order_by("created_at")
        .first()
    )
    if profile and profile.preferred_language != subscription.report_language:
        profile.preferred_language = subscription.report_language
        profile.save(update_fields=("preferred_language", "updated_at"))


@portal_admin_required
def subscription_management(request):
    query = request.GET.get("q", "").strip()
    state = request.GET.get("state", "").strip()
    subscriptions = SportsBaseSubscription.objects.select_related("player").annotate(
        match_count=Count("matches", distinct=True),
        completed_match_count=Count(
            "matches",
            filter=Q(matches__sync_state=SportsBaseMatch.SyncState.SYNCED),
            distinct=True,
        ),
    )
    if query:
        subscriptions = subscriptions.filter(
            Q(player__name__icontains=query)
            | Q(player__club__icontains=query)
            | Q(season__icontains=query)
        )
    valid_states = {value for value, _label in SportsBaseSubscription.SyncState.choices}
    if state in valid_states:
        subscriptions = subscriptions.filter(last_sync_state=state)
    else:
        state = ""
    jobs = SportsBaseSyncJob.objects.select_related("subscription__player")[:30]
    youtube_jobs = SportsBaseYouTubeUpload.objects.select_related(
        "match__subscription__player"
    )[:30]
    reports = PerformanceReport.objects.select_related(
        "subscription__player", "match"
    )[:30]
    return render(
        request,
        "sportsbase_data/subscription_management.html",
        {
            "subscriptions": subscriptions,
            "jobs": jobs,
            "youtube_jobs": youtube_jobs,
            "reports": reports,
            "query": query,
            "selected_state": state,
            "state_choices": SportsBaseSubscription.SyncState.choices,
            "active_count": sum(item.access_enabled for item in subscriptions),
        },
    )


@portal_admin_required
def subscription_form(request, pk=None):
    subscription = (
        get_object_or_404(SportsBaseSubscription, pk=pk) if pk else None
    )
    form = SportsBaseSubscriptionForm(request.POST or None, instance=subscription)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        if not item.pk:
            item.created_by = request.user
        item.save()
        _sync_direct_portal_language(item)
        generate_reports_for_subscription(item)
        messages.success(
            request,
            "L’abonnement Performance a été enregistré sans modifier la fiche du joueur.",
        )
        return redirect("performance:management")
    return render(
        request,
        "sportsbase_data/subscription_form.html",
        {"form": form, "subscription": subscription},
    )


@portal_admin_required
@require_POST
def subscription_toggle(request, pk):
    subscription = get_object_or_404(SportsBaseSubscription, pk=pk)
    action = request.POST.get("action")
    if action not in {"activate", "deactivate"}:
        messages.error(request, "Action d’abonnement invalide.")
        return redirect("performance:management")
    if action == "activate" and not subscription.player.sportsbase_url:
        messages.error(request, "Ajoutez d’abord le lien SportsBase du joueur.")
        return redirect("performance:management")
    subscription.is_active = action == "activate"
    subscription.save(update_fields=("is_active", "updated_at"))
    messages.success(
        request,
        "L’accès Performance est maintenant actif."
        if subscription.is_active
        else "L’accès Performance est désactivé ; les données restent conservées.",
    )
    return redirect("performance:management")


@portal_admin_required
@require_POST
def subscription_sync(request, pk):
    subscription = get_object_or_404(SportsBaseSubscription, pk=pk)
    if not subscription.access_enabled:
        messages.error(request, "Activez l’abonnement avant de le synchroniser.")
        return redirect("performance:management")
    job_type = request.POST.get("job_type", SportsBaseSyncJob.JobType.FULL)
    valid_types = {value for value, _label in SportsBaseSyncJob.JobType.choices}
    if job_type not in valid_types:
        job_type = SportsBaseSyncJob.JobType.FULL
    _job, created = queue_sync(
        subscription,
        requested_by=request.user,
        job_type=job_type,
    )
    messages.success(
        request,
        "La synchronisation sera lancée par l’agent local."
        if created
        else "Une synchronisation est déjà en attente ou en cours.",
    )
    return redirect("performance:management")


@portal_admin_required
@require_POST
def youtube_upload_retry(request, pk):
    upload = get_object_or_404(SportsBaseYouTubeUpload, pk=pk)
    try:
        retry_youtube_upload(upload)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "L’upload sera repris par l’agent local sans resynchroniser le match.",
        )
    return redirect("performance:management")


@portal_admin_required
def report_edit(request, pk):
    report = get_object_or_404(
        PerformanceReport.objects.select_related(
            "subscription__player", "match__youtube_upload"
        ),
        pk=pk,
    )
    form = PerformanceReportForm(request.POST or None, instance=report)
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.updated_by = request.user
        report.is_manually_edited = True
        report.published_at = (
            timezone.now()
            if report.status == PerformanceReport.Status.PUBLISHED
            else None
        )
        report.save()
        if report.match_id:
            try:
                send_ready_delivery_notification(report.match.youtube_upload)
            except SportsBaseYouTubeUpload.DoesNotExist:
                pass
        messages.success(
            request,
            "Le rapport est enregistré. Son PDF utilisera immédiatement cette version.",
        )
        return redirect("performance:report_edit", pk=report.pk)
    return render(
        request,
        "sportsbase_data/report_form.html",
        {"form": form, "report": report},
    )


@login_required
@never_cache
def report_pdf(request, pk):
    report = get_object_or_404(
        PerformanceReport.objects.select_related(
            "subscription__player", "match"
        ),
        pk=pk,
        status=PerformanceReport.Status.PUBLISHED,
    )
    if not request.user.is_superuser:
        try:
            profile = request.user.portal_profile
        except Exception as exc:
            raise Http404 from exc
        if not profile.is_active or not _portal_subscriptions_for(request.user).filter(
            pk=report.subscription_id
        ).exists():
            raise Http404
    content = render_report_pdf(report)
    response = HttpResponse(content, content_type="application/pdf")
    filename = slugify(report.title) or f"rapport-performance-{report.pk}"
    response["Content-Disposition"] = f'inline; filename="{filename}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@portal_required
def portal_performance_overview(request):
    subscriptions = list(
        _portal_subscriptions_for(request.user)
        .select_related("player")
        .prefetch_related("season_snapshots")
        .annotate(match_count=Count("matches", distinct=True))
        .order_by("player__name")
    )
    for subscription in subscriptions:
        subscription.current_snapshot = next(
            (
                snapshot
                for snapshot in subscription.season_snapshots.all()
                if snapshot.season == subscription.season
            ),
            None,
        )
    return render(
        request,
        "sportsbase_data/portal_overview.html",
        {"subscriptions": subscriptions},
    )


@never_cache
@portal_required
def portal_performance_detail(request, player_id):
    subscription = _portal_subscription_or_404(request.user, player_id)
    snapshot = subscription.season_snapshots.filter(
        season=subscription.season
    ).first()
    matches = subscription.matches.select_related("player_stats", "youtube_upload").order_by(
        "-match_date", "-sportsbase_match_id"
    )
    action_counts = {
        "available": matches.filter(
            youtube_upload__status=SportsBaseYouTubeUpload.Status.UPLOADED,
        ).count(),
        "emailed": matches.filter(
            actions_state=SportsBaseMatch.ActionsState.EMAILED
        ).count(),
        "pending": matches.filter(
            actions_state__in={
                SportsBaseMatch.ActionsState.QUEUED,
                SportsBaseMatch.ActionsState.GENERATING,
            }
        ).count(),
    }
    cycle_reports = subscription.performance_reports.filter(
        report_type=PerformanceReport.ReportType.CYCLE,
        status=PerformanceReport.Status.PUBLISHED,
    ).order_by("-cycle_number")
    season_analysis_pairs, season_analysis_other, season_average_other = (
        _build_season_analysis(snapshot)
    )
    return render(
        request,
        "sportsbase_data/portal_performance_detail.html",
        {
            "subscription": subscription,
            "player": subscription.player,
            "snapshot": snapshot,
            "matches": matches,
            "action_counts": action_counts,
            "cycle_reports": cycle_reports,
            "season_analysis_pairs": season_analysis_pairs,
            "season_analysis_other": season_analysis_other,
            "season_average_other": season_average_other,
            "portal_language": request.portal_profile.preferred_language,
        },
    )


@never_cache
@portal_required
def portal_match_detail(request, player_id, match_id):
    subscription = _portal_subscription_or_404(request.user, player_id)
    match = get_object_or_404(
        subscription.matches.select_related("player_stats", "youtube_upload"),
        sportsbase_match_id=str(match_id),
    )
    try:
        stats = match.player_stats
    except SportsBaseMatchStats.DoesNotExist:
        stats = None
    analysis_pairs, analysis_other = _build_match_analysis(stats)
    try:
        performance_report = match.performance_report
    except PerformanceReport.DoesNotExist:
        performance_report = None
    return render(
        request,
        "sportsbase_data/portal_match_detail.html",
        {
            "subscription": subscription,
            "player": subscription.player,
            "match": match,
            "stats": stats,
            "analysis_pairs": analysis_pairs,
            "analysis_other": analysis_other,
            "performance_report": performance_report,
            "portal_language": request.portal_profile.preferred_language,
        },
    )


def _png_response(content):
    if not content:
        return HttpResponse(status=404)
    response = HttpResponse(bytes(content), content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@portal_required
@require_GET
def portal_season_map(request, player_id, map_kind):
    subscription = _portal_subscription_or_404(request.user, player_id)
    snapshot = get_object_or_404(
        SportsBaseSeasonSnapshot,
        subscription=subscription,
        season=subscription.season,
    )
    if map_kind == "heatmap":
        return _png_response(snapshot.heatmap_png)
    if map_kind == "touches":
        return _png_response(snapshot.ball_touches_png)
    if map_kind == "radar":
        return _png_response(snapshot.radar_png)
    return HttpResponse(status=404)


@portal_required
@require_GET
def portal_match_map(request, player_id, match_id, map_kind):
    subscription = _portal_subscription_or_404(request.user, player_id)
    stats = get_object_or_404(
        SportsBaseMatchStats.objects.select_related("match"),
        match__subscription=subscription,
        match__sportsbase_match_id=str(match_id),
    )
    if map_kind == "heatmap":
        return _png_response(stats.heatmap_png)
    if map_kind == "touches":
        return _png_response(stats.ball_touches_png)
    return HttpResponse(status=404)


@production_required
@require_GET
def api_next_job(request):
    job = claim_next_job()
    if not job:
        return JsonResponse({"job": None})
    return JsonResponse({"job": job.payload})


@production_required
@require_POST
def api_job_result(request, job_id):
    job = get_object_or_404(SportsBaseSyncJob, pk=job_id)
    try:
        result = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"success": False, "error": "JSON invalide."}, status=400)
    try:
        finished_job = apply_sync_result(job, result)
    except ValueError as exc:
        fail_sync_job(job, exc)
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    ready_uploads = SportsBaseYouTubeUpload.objects.filter(
        match__subscription=finished_job.subscription,
        status=SportsBaseYouTubeUpload.Status.UPLOADED,
        notification_sent_at__isnull=True,
    )
    for ready_upload in ready_uploads:
        send_ready_delivery_notification(ready_upload)
    return JsonResponse(
        {
            "success": True,
            "job_id": finished_job.pk,
            "status": finished_job.status,
            "finished_at": finished_job.finished_at.isoformat(),
        }
    )


@production_required
@require_GET
def api_next_youtube_job(request):
    upload = claim_next_youtube_upload()
    if upload is None:
        return JsonResponse({"job": None})
    return JsonResponse({"job": upload.payload})


@production_required
@require_POST
def api_youtube_job_result(request, job_id):
    upload = get_object_or_404(SportsBaseYouTubeUpload, pk=job_id)
    try:
        result = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"success": False, "error": "JSON invalide."}, status=400)
    try:
        finished_upload = apply_youtube_upload_result(upload, result)
    except ValueError as exc:
        if upload.status == SportsBaseYouTubeUpload.Status.RUNNING:
            apply_youtube_upload_result(
                upload,
                {"status": SportsBaseYouTubeUpload.Status.FAILED, "error": str(exc)},
            )
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    if finished_upload.status == SportsBaseYouTubeUpload.Status.UPLOADED:
        send_ready_delivery_notification(finished_upload)
    return JsonResponse(
        {
            "success": True,
            "job_id": finished_upload.pk,
            "status": finished_upload.status,
            "youtube_url": finished_upload.youtube_url,
            "finished_at": finished_upload.finished_at.isoformat(),
        }
    )
