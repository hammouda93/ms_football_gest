"""Read-only Performance control center and authenticated passive telemetry intake.

No job is created, stopped, retried, or modified by these endpoints.
"""
import json
import re
import uuid
from datetime import timedelta

from django.db.models import Count
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from client_portal.decorators import portal_admin_required, production_required
from .services import active_subscriptions
from .monitoring_history import current_issue_digest
from .models import (
    PerformanceAgentEvent,
    PerformanceAgentRun,
    SportsBaseSyncJob,
)


KINDS = {
    "started", "stopped", "plan", "queued", "job_started", "job_finished",
    "progress", "warning", "error",
}
LEVELS = {"info", "warning", "error"}
RUN_STATES = {"running", "finished"}


def _string(value, maximum):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _integer(value, *, minimum=0, maximum=2147483647):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if minimum <= result <= maximum else None


@production_required
@require_POST
def ingest_monitor_events(request):
    """Best-effort telemetry. The agent itself has its own independent API."""
    if len(request.body) > 25000:
        return JsonResponse({"error": "Taille excessive"}, status=413)
    try:
        payload = json.loads(request.body)
        run_id = uuid.UUID(str(payload["run_id"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return JsonResponse({"error": "Session invalide"}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("events", []), list):
        return JsonResponse({"error": "Événements invalides"}, status=400)
    incoming = payload.get("events", [])
    if len(incoming) > 30:
        return JsonResponse({"error": "Trop d'événements"}, status=400)
    worker_name = _string(payload.get("worker_name"), 100)
    if not worker_name:
        return JsonResponse({"error": "Worker non identifié"}, status=400)
    state = payload.get("state", "running")
    if state not in RUN_STATES:
        return JsonResponse({"error": "État invalide"}, status=400)

    run, _created = PerformanceAgentRun.objects.get_or_create(
        run_id=run_id, defaults={"worker_name": worker_name},
    )
    updates = set()
    now = timezone.now()
    run.last_seen_at = now
    updates.add("last_seen_at")
    if state == "finished" and run.ended_at is None:
        run.ended_at = now
        run.state = "finished"
        updates.update(("ended_at", "state"))

    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        sequence = _integer(raw.get("sequence"), minimum=1)
        kind = _string(raw.get("kind"), 24)
        if not sequence or kind not in KINDS:
            continue
        level = _string(raw.get("level", "info"), 12)
        if level not in LEVELS:
            level = "info"
        job_id = _integer(raw.get("job_id"), minimum=1)
        event, created = PerformanceAgentEvent.objects.get_or_create(
            run=run, sequence=sequence,
            defaults={
                "kind": kind,
                "level": level,
                "message": _string(raw.get("message"), 320),
                "player": _string(raw.get("player"), 160),
                "job_id": job_id,
                "match_id": _string(raw.get("match_id"), 32),
                "stage": _string(raw.get("stage"), 80),
            },
        )
        if not created or sequence <= run.last_sequence:
            continue
        run.last_sequence = sequence
        updates.add("last_sequence")
        if event.stage:
            run.current_stage = event.stage
            updates.add("current_stage")
        if kind == "plan":
            match = re.search(r"(\d+) joueurs, (\d+) tâches", event.message)
            if match:
                run.planned_jobs = int(match.group(2))
                updates.add("planned_jobs")
        if kind == "job_started":
            run.current_job_id = job_id
            run.current_player = event.player
            run.current_match_id = ""
            updates.update(("current_job_id", "current_player", "current_match_id"))
        elif kind == "job_finished":
            run.current_job_id = None
            run.current_player = ""
            run.current_match_id = ""
            updates.update(("current_job_id", "current_player", "current_match_id"))
        elif event.match_id:
            run.current_match_id = event.match_id
            updates.add("current_match_id")

    if updates:
        run.save(update_fields=list(updates))
    return JsonResponse({"ok": True, "received": len(incoming)})


def _iso(value):
    return value.isoformat() if value else None


@portal_admin_required
@require_GET
def monitor_snapshot(request):
    """Compact polling payload; no remote control or confidential log output."""
    now = timezone.now()
    stale_threshold = now - timedelta(seconds=90)
    workers = []
    for run in PerformanceAgentRun.objects.order_by("-started_at", "-pk")[:6]:
        live = run.state == "running" and run.last_seen_at >= stale_threshold
        workers.append({
            "run_id": str(run.run_id),
            "name": run.worker_name,
            "state": "active" if live else ("stopped" if run.ended_at else "offline"),
            "started_at": _iso(run.started_at),
            "last_seen_at": _iso(run.last_seen_at),
            "ended_at": _iso(run.ended_at),
            "planned_jobs": run.planned_jobs,
            "current_player": run.current_player if live else "",
            "current_job_id": run.current_job_id if live else None,
            "current_match_id": run.current_match_id if live else "",
            "stage": run.current_stage if live else "",
            "finished_jobs": run.events.filter(kind="job_finished").count(),
        })

    current_run = next((item for item in workers if item["state"] == "active"), None)
    events = []
    selected = PerformanceAgentEvent.objects.select_related("run")
    if current_run:
        selected = selected.filter(run__run_id=current_run["run_id"])
    else:
        latest_run_id = workers[0]["run_id"] if workers else None
        selected = selected.filter(run__run_id=latest_run_id) if latest_run_id else selected.none()
    for event in selected.order_by("-created_at", "-pk")[:75]:
        events.append({
            "at": _iso(event.created_at),
            "message": event.message,
            "kind": event.kind,
            "level": event.level,
            "player": event.player,
            "job_id": event.job_id,
            "match_id": event.match_id,
            "stage": event.stage,
        })

    state_counts = dict(
        SportsBaseSyncJob.objects.values("status").annotate(amount=Count("pk"))
        .values_list("status", "amount")
    )
    jobs = [
        {
            "id": job.pk,
            "player": job.subscription.player.name,
            "type": job.get_job_type_display(),
            "status": job.status,
            "created_at": _iso(job.created_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "matches": (job.result_summary or {}).get("matches_received", 0),
            "error": (job.error_message or "")[:230],
        }
        for job in SportsBaseSyncJob.objects.select_related(
            "subscription__player"
        ).filter(
            status__in=(SportsBaseSyncJob.Status.PENDING, SportsBaseSyncJob.Status.RUNNING)
        ).order_by("created_at", "pk")[:300]
    ]
    digest = current_issue_digest()
    missing = digest['issues'][:25]

    return JsonResponse({
        "now": _iso(now),
        "workers": workers,
        "events": events,
        "jobs": jobs,
        "missing_matches": missing,
        "metrics": {
            "subscriptions": active_subscriptions().count(),
            "waiting": state_counts.get(SportsBaseSyncJob.Status.PENDING, 0),
            "running": state_counts.get(SportsBaseSyncJob.Status.RUNNING, 0),
            "finished": state_counts.get(SportsBaseSyncJob.Status.SUCCESS, 0),
            "failed": state_counts.get(SportsBaseSyncJob.Status.FAILED, 0),
            "partial": state_counts.get(SportsBaseSyncJob.Status.PARTIAL, 0),
            "open_matches": digest["open_matches"],
            "open_players": digest["open_players"],
            "pending_matches": digest["pending_matches"],
        },
    })
