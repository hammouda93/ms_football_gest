"""Read-only V2 history and current-issue diagnostics for MS Performance.

No endpoints here claim jobs, control the Windows worker, generate videos, or
modify match data. An issue disappears when the underlying match is repaired.
"""
from datetime import date, timedelta
from uuid import UUID

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from client_portal.decorators import portal_admin_required
from .analysis_engine import SPORTSBASE_PLAYER_COLUMNS
from .models import (
    PerformanceAgentEvent, PerformanceAgentRun, SportsBaseMatch,
    SportsBaseSyncJob,
)
from .services import active_subscriptions


REQUIRED_HEADERS = {str(name).casefold().strip() for name in SPORTSBASE_PLAYER_COLUMNS}
PER_PAGE = 20


def _iso(value):
    return value.isoformat() if value else None


def _clean_query(request):
    return str(request.GET.get("q", "") or "").strip()[:100]


def _date_filter(queryset, request, field):
    for param, suffix in (("from", "gte"), ("to", "lte")):
        value = request.GET.get(param, "")
        try:
            day = date.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        queryset = queryset.filter(**{field + "__date__" + suffix: day})
    return queryset


def _page(items, request):
    page = Paginator(items, PER_PAGE).get_page(request.GET.get("page", "1"))
    return {
        "items": list(page.object_list),
        "page": page.number,
        "pages": page.paginator.num_pages,
        "total": page.paginator.count,
        "has_next": page.has_next(),
        "has_previous": page.has_previous(),
    }


def _run_state(run, now=None):
    now = now or timezone.now()
    if run.ended_at:
        return "stopped"
    if run.state == "running" and run.last_seen_at >= now - timedelta(seconds=90):
        return "active"
    return "offline"


def _run_json(run):
    return {
        "id": str(run.run_id),
        "worker": run.worker_name,
        "status": _run_state(run),
        "started_at": _iso(run.started_at),
        "last_seen_at": _iso(run.last_seen_at),
        "ended_at": _iso(run.ended_at),
        "planned_jobs": run.planned_jobs,
        "completed_jobs": getattr(run, "completed_jobs", None),
        "current_player": run.current_player,
        "stage": run.current_stage,
    }


def _job_json(job):
    return {
        "id": job.pk, "player": job.subscription.player.name,
        "player_id": job.subscription.player_id,
        "type": job.get_job_type_display(), "status": job.status,
        "created_at": _iso(job.created_at), "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at), "attempts": job.attempts,
        "result": job.result_summary or {}, "error": (job.error_message or "")[:400],
    }


def _event_json(item):
    return {
        "id": item.pk, "at": _iso(item.created_at),
        "run_id": str(item.run.run_id),
        "worker": item.run.worker_name,
        "job_id": item.job_id, "player": item.player,
        "match_id": item.match_id, "stage": item.stage,
        "kind": item.kind, "level": item.level, "message": item.message,
    }


def _match_info(match):
    """Status recorded in DB, not unverified disk presence or PDF generation."""
    try:
        stats = match.player_stats
        available = {str(header).casefold().strip() for header in (stats.players_statistics_headers or ())}
        kpis = len(REQUIRED_HEADERS.intersection(available))
        stats_ok = kpis == len(REQUIRED_HEADERS) and bool(stats.players_statistics_rows)
    except (AttributeError, SportsBaseMatch.player_stats.RelatedObjectDoesNotExist):
        kpis, stats_ok = 0, False
    try:
        report = match.performance_report
        analysis_ok = bool((report.analysis_payload or {}).get("available"))
        report_state = report.status
    except (AttributeError, SportsBaseMatch.performance_report.RelatedObjectDoesNotExist):
        analysis_ok, report_state = False, "absent"

    video_enabled = match.subscription.all_actions_enabled
    video_ok = (not video_enabled or match.actions_state in (
        SportsBaseMatch.ActionsState.DOWNLOADED,
        SportsBaseMatch.ActionsState.EMAILED,
    ))
    pending = match.sync_state == SportsBaseMatch.SyncState.DISCOVERED
    reasons = []
    if not stats_ok:
        reasons.append("Statistiques Players incomplètes")
    if not analysis_ok:
        reasons.append("Analyse du rapport indisponible")
    if not video_ok:
        reasons.append("All Actions non terminée")
    if match.sync_state == SportsBaseMatch.SyncState.FAILED:
        reasons.append("Synchronisation échouée")
    if match.actions_state == SportsBaseMatch.ActionsState.FAILED:
        reasons.append("Téléchargement vidéo échoué")
    issue_state = "complete" if not reasons else "pending" if pending else "open"
    return {
        "match_id": match.sportsbase_match_id,
        "player": match.subscription.player.name,
        "player_id": match.subscription.player_id,
        "fixture": str(match), "date": _iso(match.match_date),
        "updated_at": _iso(match.updated_at),
        "sync_state": match.sync_state,
        "video_state": match.actions_state,
        "video_state_verified_on_disk": False,
        "statistics_complete": stats_ok, "kpis_found": kpis,
        "kpis_required": len(REQUIRED_HEADERS),
        "analysis_available": analysis_ok,
        "report_state": report_state,
        "pdf_on_windows_verified": False,
        "issue_state": issue_state, "reasons": reasons,
    }


def current_issue_digest():
    """All active subscriptions/current-season matches; cache for 60s.

    Counts unique remaining player/match gaps, not accumulated historical jobs.
    Never loads the PNG/BinaryField maps into the dashboard.
    """
    key = "performance:monitor:v2:current_match_issues"
    cached = cache.get(key)
    if cached is not None:
        return cached
    active = active_subscriptions()
    matches = (
        SportsBaseMatch.objects.filter(subscription__in=active)
        .select_related("subscription__player", "player_stats", "performance_report")
        .only(
            "id", "subscription_id", "sportsbase_match_id", "season", "match_date",
            "home_team", "away_team", "sync_state", "actions_state", "updated_at",
            "subscription__player__name", "subscription__player_id",
            "subscription__all_actions_enabled", "subscription__season",
            "player_stats__players_statistics_headers",
            "player_stats__players_statistics_rows",
            "performance_report__status", "performance_report__analysis_payload",
        )
        .order_by("-updated_at", "-pk")
    )
    # Current-season equality is checked against each row's own subscription.
    results = []
    players = set()
    pending = 0
    for match in matches.iterator(chunk_size=100):
        if match.season != match.subscription.season:
            continue
        info = _match_info(match)
        if info["issue_state"] == "complete":
            continue
        if info["issue_state"] == "pending":
            pending += 1
        else:
            players.add(match.subscription.player_id)
        results.append(info)
    result = {
        "issues": results,
        "open_matches": sum(item["issue_state"] == "open" for item in results),
        "open_players": len(players),
        "pending_matches": pending,
    }
    cache.set(key, result, timeout=60)
    return result


@portal_admin_required
@require_GET
def monitoring_history(request):
    section = str(request.GET.get("kind", "sessions"))[:24]
    q = _clean_query(request)
    status = str(request.GET.get("status", ""))[:24]

    if section == "sessions":
        qs = PerformanceAgentRun.objects.order_by("-started_at", "-pk")
        qs = _date_filter(qs, request, "started_at")
        if q:
            qs = qs.filter(Q(worker_name__icontains=q) |
                           Q(events__player__icontains=q) |
                           Q(events__match_id__icontains=q) |
                           Q(events__message__icontains=q)).distinct()
        if status in ("active", "offline", "stopped"):
            # Presence is derived from heartbeat rather than stale state strings.
            if status == "stopped":
                qs = qs.filter(ended_at__isnull=False)
            elif status == "active":
                qs = qs.filter(ended_at__isnull=True,
                               last_seen_at__gte=timezone.now() - timedelta(seconds=90))
            else:
                qs = qs.filter(ended_at__isnull=True,
                               last_seen_at__lt=timezone.now() - timedelta(seconds=90))
        page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page", "1"))
        return JsonResponse({
            "kind": section, "items": [_run_json(x) for x in page],
            "page": page.number, "pages": page.paginator.num_pages,
            "total": page.paginator.count,
        })

    if section == "jobs":
        qs = SportsBaseSyncJob.objects.select_related("subscription__player").order_by("-created_at", "-pk")
        qs = _date_filter(qs, request, "created_at")
        if q:
            qs = qs.filter(Q(subscription__player__name__icontains=q) |
                           Q(error_message__icontains=q) |
                           Q(subscription__matches__sportsbase_match_id__icontains=q)).distinct()
        if status in ("pending", "running", "success", "partial", "failed"):
            qs = qs.filter(status=status)
        page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page", "1"))
        return JsonResponse({
            "kind": section, "items": [_job_json(x) for x in page],
            "page": page.number, "pages": page.paginator.num_pages,
            "total": page.paginator.count,
        })

    if section == "events":
        qs = PerformanceAgentEvent.objects.select_related("run").order_by("-created_at", "-pk")
        qs = _date_filter(qs, request, "created_at")
        run_id = request.GET.get("run_id")
        if run_id:
            try:
                qs = qs.filter(run__run_id=UUID(str(run_id)))
            except ValueError:
                return JsonResponse({"error": "Session invalide"}, status=400)
        job_id = request.GET.get("job_id")
        if job_id:
            try:
                qs = qs.filter(job_id=int(job_id))
            except (ValueError, TypeError):
                return JsonResponse({"error": "Tâche invalide"}, status=400)
        if q:
            qs = qs.filter(Q(message__icontains=q) | Q(player__icontains=q) |
                           Q(match_id__icontains=q) | Q(run__worker_name__icontains=q))
        if status in ("info", "warning", "error"):
            qs = qs.filter(level=status)
        page = Paginator(qs, PER_PAGE).get_page(request.GET.get("page", "1"))
        return JsonResponse({
            "kind": section, "items": [_event_json(x) for x in page],
            "page": page.number, "pages": page.paginator.num_pages,
            "total": page.paginator.count,
        })

    if section == "issues":
        digest = current_issue_digest()
        issues = digest["issues"]
        if q:
            folded = q.casefold()
            issues = [item for item in issues if folded in
                      (" ".join((item["player"], item["fixture"], item["match_id"],
                                 " ".join(item["reasons"])))).casefold()]
        if status in ("open", "pending"):
            issues = [item for item in issues if item["issue_state"] == status]
        start, end = request.GET.get("from"), request.GET.get("to")
        for bound, day, operator in (("from", start, lambda a, b: a >= b),
                                     ("to", end, lambda a, b: a <= b)):
            try:
                wanted = date.fromisoformat(day)
            except (TypeError, ValueError):
                continue
            issues = [item for item in issues if item["updated_at"] and
                      operator(date.fromisoformat(item["updated_at"][:10]), wanted)]
        result = _page(issues, request)
        result["kind"] = section
        result["counts"] = {
            "open_matches": digest["open_matches"],
            "open_players": digest["open_players"],
            "pending_matches": digest["pending_matches"],
        }
        return JsonResponse(result)
    return JsonResponse({"error": "Section inconnue"}, status=400)


@portal_admin_required
@require_GET
def monitoring_session_detail(request, run_id):
    try:
        run = PerformanceAgentRun.objects.get(run_id=run_id)
    except PerformanceAgentRun.DoesNotExist:
        return JsonResponse({"error": "Session introuvable"}, status=404)
    history = run.events.order_by("sequence").values(
        "kind", "player", "job_id", "match_id", "message", "created_at")
    planned, handled, seen_planned, seen_handled = [], [], set(), set()
    for item in history.iterator(chunk_size=100):
        if item["kind"] == "queued" and item["job_id"] not in seen_planned:
            planned.append({"job_id": item["job_id"], "player": item["player"]})
            seen_planned.add(item["job_id"])
        if item["kind"] == "job_started" and item["job_id"] not in seen_handled:
            handled.append({"job_id": item["job_id"], "player": item["player"]})
            seen_handled.add(item["job_id"])
    return JsonResponse({
        "session": _run_json(run), "planned_players": planned,
        "processed_players": handled, "events_total": run.events.count(),
        "note": "Journal des étapes observées; anciennes sessions sans supervision non reconstituables.",
    })


@portal_admin_required
@require_GET
def monitoring_job_detail(request, job_id):
    try:
        job = SportsBaseSyncJob.objects.select_related(
            "subscription__player"
        ).get(pk=job_id)
    except SportsBaseSyncJob.DoesNotExist:
        return JsonResponse({"error": "Tâche introuvable"}, status=404)
    ids = (job.result_summary or {}).get("match_ids", [])
    if not isinstance(ids, list):
        ids = []
    matches = (
        SportsBaseMatch.objects.filter(subscription=job.subscription, sportsbase_match_id__in=ids[:300])
        .select_related("subscription__player", "player_stats", "performance_report",
                        "youtube_upload", "dailymotion_upload")
        .only(
            "id", "subscription_id", "sportsbase_match_id", "season", "match_date",
            "home_team", "away_team", "sync_state", "actions_state", "updated_at",
            "subscription__player__name", "subscription__player_id",
            "subscription__all_actions_enabled", "player_stats__players_statistics_headers",
            "player_stats__players_statistics_rows", "performance_report__status",
            "performance_report__analysis_payload",
            "youtube_upload__status", "youtube_upload__youtube_url",
            "dailymotion_upload__status", "dailymotion_upload__dailymotion_url",
        )
    )
    info = []
    for match in matches:
        item = _match_info(match)
        try:
            item["youtube"] = match.youtube_upload.status
        except SportsBaseMatch.youtube_upload.RelatedObjectDoesNotExist:
            item["youtube"] = "non demandé"
        try:
            item["dailymotion"] = match.dailymotion_upload.status
        except SportsBaseMatch.dailymotion_upload.RelatedObjectDoesNotExist:
            item["dailymotion"] = "non demandé"
        info.append(item)
    return JsonResponse({
        "job": _job_json(job),
        "matches": info,
        "tracked_matches": len(ids),
        "note": "Les états de match reflètent les données actuelles; le journal horodaté reflète l'exécution historique.",
    })
