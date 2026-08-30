import json
from collections import Counter, defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import slugify
from django.urls import reverse
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

from .analysis_engine import ms_rating, platform_index
from .forms import (
    PerformanceReportForm,
    PerformanceSubscriptionPaymentForm,
    SportsBaseSubscriptionForm,
)
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
    pending_jobs_overview,
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


# Keep the same reading order as the season statistics supplied to the analyst.
# Passes remain supported when the competition exposes them, without disturbing
# the reference order used by the season panel.
SEASON_METRIC_PAIRS = (
    ("Key passes", None, "fa-key"),
    ("Shots", "Shots on target, %", "fa-bullseye"),
    ("Crosses", "Crosses accurate, %", "fa-arrows-left-right-to-line"),
    ("Challenges", "Challenges won, %", "fa-people-arrows-left-right"),
    (
        "Aerial challenges",
        "Aerial challenges won, %",
        "fa-arrow-up-wide-short",
    ),
    ("Dribbles", "Dribbles successful, %", "fa-person-running"),
    ("Tackles", "Tackles successful, %", "fa-shield-halved"),
    ("Passes", "Passes accurate, %", "fa-share-nodes"),
)

SEASON_KPI_KEYS = {
    "index",
    "matches played",
    "goals",
    "assists",
    "time on the field, %",
}


SEASON_SUCCESS_COUNTS = {
    "Passes accurate, %": "Passes accurate",
    "Shots on target, %": "Shots on target",
    "Crosses accurate, %": "Crosses accurate",
    "Challenges won, %": "Challenges won",
    "Aerial challenges won, %": "Aerial challenges won",
    "Dribbles successful, %": "Dribbles successful",
    "Tackles successful, %": "Tackles successful",
}


def _stat_number(value, *, dash_is_zero=False):
    """Convert one collected statistic without confusing absence and zero."""
    if value is None or isinstance(value, bool):
        return 0.0 if dash_is_zero else None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace("%", "").replace(",", ".")
    if cleaned.casefold() in {"", "-", "–", "—", "none", "null", "nan"}:
        return 0.0 if dash_is_zero else None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _display_number(value, digits=2):
    if value is None:
        return None
    rounded = round(float(value), digits)
    return int(rounded) if rounded.is_integer() else rounded


def _display_percent(value):
    number = _display_number(value, 1)
    return None if number is None else f"{number}%"


def _match_statistics_map(stats):
    return _normalized_statistics(
        stats.summary_statistics,
        stats.success_rates,
        stats.detailed_statistics,
    )


def _season_rate(match_values, metric_name, rate_name):
    """Weight a season success rate by attempts, with a safe mean fallback."""
    metric_key = metric_name.casefold()
    rate_key = rate_name.casefold()
    success_key = SEASON_SUCCESS_COUNTS.get(rate_name, "").casefold()
    attempts_total = 0.0
    successes_total = 0.0
    simple_rates = []

    for values in match_values:
        attempts_item = values.get(metric_key)
        rate_item = values.get(rate_key)
        success_item = values.get(success_key) if success_key else None
        attempts = (
            _stat_number(attempts_item.get("value"), dash_is_zero=True)
            if attempts_item is not None
            else 0.0
        )
        rate = (
            _stat_number(rate_item.get("value"), dash_is_zero=True)
            if rate_item is not None
            else None
        )
        if rate is not None:
            if abs(rate) <= 1 and "%" not in str(rate_item.get("value")):
                rate *= 100
            simple_rates.append(rate)
        successes = (
            _stat_number(success_item.get("value"), dash_is_zero=True)
            if success_item is not None
            else None
        )
        if attempts > 0 and (successes is not None or rate is not None):
            attempts_total += attempts
            successes_total += successes if successes is not None else attempts * rate / 100

    if attempts_total > 0:
        return max(0.0, min(100.0, successes_total / attempts_total * 100))
    if simple_rates:
        return max(0.0, min(100.0, sum(simple_rates) / len(simple_rates)))
    return None


def _build_tracked_season(matches):
    """Aggregate the season exclusively from matches analysed in this portal."""
    analysed = [match for match in matches if getattr(match, "player_stats", None)]
    match_values = [_match_statistics_map(match.player_stats) for match in analysed]
    match_count = len(analysed)

    if not match_count:
        return {
            "summary": {"match_count": 0},
            "pairs": [],
            "other": [],
            "missions": [],
        }

    def metric_total(name):
        key = name.casefold()
        return sum(
            _stat_number(values[key].get("value"), dash_is_zero=True)
            if key in values
            else 0.0
            for values in match_values
        )

    indexes = [
        _stat_number(platform_index(match.player_stats.index))
        for match in analysed
        if match.player_stats.index is not None
    ]
    minutes = [
        float(match.player_stats.minutes_played or 0)
        for match in analysed
    ]
    minutes_total = sum(minutes)
    summary = {
        "match_count": match_count,
        "index_average": (
            _display_number(sum(indexes) / len(indexes), 1)
            if indexes
            else None
        ),
        "goals": _display_number(metric_total("Goals")),
        "assists": _display_number(metric_total("Assists")),
        "minutes_total": _display_number(minutes_total),
        "minutes_average": _display_number(minutes_total / match_count, 1),
        "time_share": _display_percent(minutes_total / (match_count * 90) * 100),
    }

    pairs = []
    consumed = set(SEASON_KPI_KEYS) | {"minutes played"}
    for metric_name, rate_name, icon in SEASON_METRIC_PAIRS:
        metric_key = metric_name.casefold()
        if not any(metric_key in values for values in match_values):
            continue
        total = metric_total(metric_name)
        rate = _season_rate(match_values, metric_name, rate_name) if rate_name else None
        consumed.add(metric_key)
        if rate_name:
            consumed.add(rate_name.casefold())
            success_name = SEASON_SUCCESS_COUNTS.get(rate_name)
            if success_name:
                consumed.add(success_name.casefold())
        pairs.append(
            {
                "name": metric_name,
                "value": _display_number(total / match_count),
                "total_value": _display_number(total),
                "rate_name": rate_name,
                "rate_value": _display_percent(rate),
                "chart_percent": round(rate, 1) if rate is not None else 0,
                "has_rate": rate is not None,
                "icon": icon,
            }
        )

    all_names = {}
    for values in match_values:
        for key, item in values.items():
            all_names.setdefault(key, item.get("name") or key)
    other = []
    for key, name in all_names.items():
        if key in consumed or key.endswith(", %"):
            continue
        available = [values[key] for values in match_values if key in values]
        if not available:
            continue
        numbers = []
        for item in available:
            raw_value = item.get("value")
            number = _stat_number(raw_value)
            if number is None and str(raw_value).strip() not in {"-", "–", "—"}:
                continue
            numbers.append(number or 0.0)
        if not numbers:
            continue
        total = sum(numbers)
        other.append(
            {
                "name": name,
                "total_value": _display_number(total),
                "average_value": _display_number(total / match_count),
            }
        )
    other.sort(key=lambda item: str(item["name"]).casefold())

    mission_buckets = defaultdict(
        lambda: {
            "labels": Counter(),
            "scores": [],
            "weights": [],
            "kpis": Counter(),
        }
    )
    for match in analysed:
        report = getattr(match, "performance_report", None)
        if report and (
            report.status != PerformanceReport.Status.PUBLISHED
            or report.report_type != PerformanceReport.ReportType.MATCH
        ):
            report = None
        analysis = (
            report.analysis_payload
            if report and isinstance(report.analysis_payload, dict)
            else {}
        )
        dimensions = (
            analysis.get("dimensions")
            or (analysis.get("score_breakdown") or {}).get("dimensions")
            or []
        )
        for order, dimension in enumerate(dimensions):
            if not isinstance(dimension, dict):
                continue
            key = str(
                dimension.get("key")
                or dimension.get("label")
                or f"mission-{order}"
            )
            score = _stat_number(dimension.get("score"))
            if score is None:
                continue
            bucket = mission_buckets[key]
            bucket["labels"][str(dimension.get("label") or key)] += 1
            bucket["scores"].append(score)
            weight = _stat_number(
                dimension.get("effective_weight") or dimension.get("weight")
            )
            if weight is not None:
                bucket["weights"].append(weight)
            evidence = dimension.get("headline_evidence") or dimension.get("evidence") or []
            for item in evidence:
                if isinstance(item, dict) and item.get("metric"):
                    bucket["kpis"][str(item["metric"])] += 1

    missions = []
    for key, bucket in mission_buckets.items():
        score = sum(bucket["scores"]) / len(bucket["scores"])
        average_weight = (
            sum(bucket["weights"]) / len(bucket["weights"])
            if bucket["weights"]
            else 0
        )
        missions.append(
            {
                "key": key,
                "label": bucket["labels"].most_common(1)[0][0],
                "rating_10": round(max(0.0, min(100.0, score)) / 10, 1),
                "chart_percent": round(max(0.0, min(100.0, score)), 1),
                "weight": _display_number(average_weight, 1),
                "match_count": len(bucket["scores"]),
                "kpis": [name for name, _ in bucket["kpis"].most_common(3)],
            }
        )
    missions.sort(key=lambda item: (-float(item["weight"] or 0), item["label"]))
    return {"summary": summary, "pairs": pairs, "other": other, "missions": missions}


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
    # Goals, assists and key passes already form the priority impact strip at
    # the top of the page.  Do not repeat them again in "other markers".
    consumed = {
        "index",
        "minutes played",
        "goals",
        "assists",
        "key passes",
        "key passes accurate, %",
    }
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


def _build_match_headline(report):
    """Return the decisive, player-facing summary displayed before all detail."""
    if report is None or not isinstance(report.analysis_payload, dict):
        return None
    analysis = report.analysis_payload
    if not analysis.get("available"):
        return None
    appendix = {
        str(item.get("metric") or ""): item
        for item in (analysis.get("appendix_metrics") or [])
        if isinstance(item, dict)
    }

    def metric_value(name):
        item = appendix.get(name) or {}
        value = item.get("display")
        return "0" if value in {None, "", "-", "–", "—"} else value

    verdict = analysis.get("verdict") or {}
    player = analysis.get("player") or {}
    score = verdict.get("score")
    if score is None:
        score = player.get("profile_score")
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    tone = str(verdict.get("tone") or "neutral")
    if tone not in {"excellent", "positive", "warning", "danger", "neutral"}:
        tone = "neutral"
    return {
        "goals": metric_value("Goals"),
        "assists": metric_value("Assists"),
        "key_passes": metric_value("Key passes"),
        "ms_score": score,
        "rating_10": verdict.get("rating_10") or player.get("rating_10") or ms_rating(score),
        "verdict": str(verdict.get("label") or "—"),
        "tone": tone,
    }


def _build_season_analysis(snapshot):
    """Pair season action volumes with success rates and per-match rhythm."""
    if snapshot is None:
        return [], [], []

    totals = _normalized_statistics(snapshot.season_statistics)
    averages = _normalized_statistics(snapshot.average_statistics)
    consumed = set(SEASON_KPI_KEYS) | {"minutes played"}
    pairs = []

    for metric_name, rate_name, icon in SEASON_METRIC_PAIRS:
        metric_key = metric_name.casefold()
        rate_key = rate_name.casefold() if rate_name else None
        metric = totals.get(metric_key)
        average = averages.get(metric_key)
        rate = (totals.get(rate_key) or averages.get(rate_key)) if rate_key else None
        if metric is None and rate is None and average is None:
            continue
        consumed.add(metric_key)
        if rate_key:
            consumed.add(rate_key)
        rate_value = rate.get("value") if rate else None
        chart_percent = _percentage_for_chart(rate_value)
        value_is_average = metric is None and average is not None
        pairs.append(
            {
                "name": metric_name,
                "value": (
                    metric.get("value")
                    if metric
                    else average.get("value") if average else None
                ),
                "value_is_average": value_is_average,
                "average_value": (
                    average.get("value")
                    if average and not value_is_average
                    else None
                ),
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


def _season_table_rows_with_ms_index(snapshot):
    """Apply the MS index scale to the secondary season table only."""
    if snapshot is None:
        return []
    headers = list(snapshot.season_table_headers or [])
    try:
        index_position = next(
            index
            for index, header in enumerate(headers)
            if str(header).strip().casefold() == "index"
        )
    except StopIteration:
        index_position = None
    rows = []
    for source in snapshot.season_match_rows or []:
        item = dict(source) if isinstance(source, dict) else {"values": source}
        values = list(item.get("values") or [])
        if index_position is not None and index_position < len(values):
            values[index_position] = platform_index(values[index_position])
        item["values"] = values
        rows.append(item)
    return rows


def _time_on_field_display(snapshot):
    """Format the playing-time percentage without ever producing `—%`."""
    if snapshot is None:
        return "—"
    value = snapshot.time_on_field_percent
    if value is None:
        item = _normalized_statistics(snapshot.season_statistics).get(
            "time on the field, %"
        )
        value = item.get("value") if item else None
    if value is None:
        return "—"
    text = str(value).strip()
    if not text or text.casefold() in {"-", "–", "—", "none", "null", "nan"}:
        return "—"
    if text.endswith(".0"):
        text = text[:-2]
    return text if text.endswith("%") else f"{text}%"


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
        {
            "form": form,
            "subscription": subscription,
            "payments": subscription.payments.all() if subscription else (),
            "payment_form": PerformanceSubscriptionPaymentForm(
                subscription=subscription,
                initial={
                    "amount": subscription.remaining_balance,
                    "payment_date": timezone.localdate(),
                }
                if subscription and subscription.remaining_balance > 0
                else {"payment_date": timezone.localdate()},
            )
            if subscription
            else None,
        },
    )


@portal_admin_required
@require_POST
def subscription_payment_add(request, pk):
    subscription = get_object_or_404(SportsBaseSubscription, pk=pk)
    form = PerformanceSubscriptionPaymentForm(
        request.POST,
        subscription=subscription,
    )
    if form.is_valid():
        payment = form.save(commit=False)
        payment.subscription = subscription
        payment.created_by = request.user
        payment.save()
        messages.success(
            request,
            f"Paiement de {payment.amount:.2f} {subscription.currency} enregistré.",
        )
    else:
        messages.error(
            request,
            "Le paiement n’a pas été enregistré : "
            + " ".join(
                error
                for errors in form.errors.values()
                for error in errors
            ),
        )
    return redirect("performance:subscription_edit", pk=subscription.pk)


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
            send_ready_delivery_notification(report)
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


@production_required
@require_GET
def api_report_pdf(request, pk):
    """Authenticated PDF download dedicated to the local production agent."""
    report = get_object_or_404(
        PerformanceReport.objects.select_related(
            "subscription__player", "match"
        ),
        pk=pk,
        status=PerformanceReport.Status.PUBLISHED,
        report_type=PerformanceReport.ReportType.MATCH,
    )
    content = render_report_pdf(report)
    response = HttpResponse(content, content_type="application/pdf")
    match_id = report.match.sportsbase_match_id if report.match_id else report.pk
    response["Content-Disposition"] = (
        f'attachment; filename="MS_Performance__match_{match_id}.pdf"'
    )
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
    matches = subscription.matches.select_related(
        "player_stats", "youtube_upload", "performance_report"
    ).order_by("-match_date", "-sportsbase_match_id")
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
    matches = list(matches)
    tracked_season = _build_tracked_season(
        [match for match in matches if match.season == subscription.season]
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
            "tracked_season_summary": tracked_season["summary"],
            "tracked_season_pairs": tracked_season["pairs"],
            "tracked_season_other": tracked_season["other"],
            "tracked_season_missions": tracked_season["missions"],
            "season_match_rows": _season_table_rows_with_ms_index(snapshot),
            "time_on_field_display": _time_on_field_display(snapshot),
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
    match_headline = _build_match_headline(performance_report)
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
            "match_headline": match_headline,
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
def api_pending_jobs(request):
    return JsonResponse(pending_jobs_overview())


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
    imported_match_ids = finished_job.result_summary.get("match_ids", ())
    report_downloads = [
        {
            "match_id": report.match.sportsbase_match_id,
            "download_url": reverse(
                "performance:api_report_pdf", args=(report.pk,)
            ),
            "filename": (
                f"MS_Performance__match_{report.match.sportsbase_match_id}.pdf"
            ),
        }
        for report in PerformanceReport.objects.select_related("match").filter(
            subscription=finished_job.subscription,
            report_type=PerformanceReport.ReportType.MATCH,
            status=PerformanceReport.Status.PUBLISHED,
            match__sportsbase_match_id__in=imported_match_ids,
        )
    ]
    ready_reports = PerformanceReport.objects.filter(
        subscription=finished_job.subscription,
        report_type=PerformanceReport.ReportType.MATCH,
        status=PerformanceReport.Status.PUBLISHED,
        match__sportsbase_match_id__in=imported_match_ids,
        notification_sent_at__isnull=True,
    )
    for ready_report in ready_reports:
        send_ready_delivery_notification(ready_report)
    return JsonResponse(
        {
            "success": True,
            "job_id": finished_job.pk,
            "status": finished_job.status,
            "finished_at": finished_job.finished_at.isoformat(),
            "reports": report_downloads,
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
        try:
            report = finished_upload.match.performance_report
        except PerformanceReport.DoesNotExist:
            pass
        else:
            send_ready_delivery_notification(report)
    return JsonResponse(
        {
            "success": True,
            "job_id": finished_upload.pk,
            "status": finished_upload.status,
            "youtube_url": finished_upload.youtube_url,
            "finished_at": finished_upload.finished_at.isoformat(),
        }
    )
