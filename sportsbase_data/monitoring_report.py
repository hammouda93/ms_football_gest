"""Simple read-only agent report backed by persisted MS Football job results.

The report is deliberately independent from Windows session telemetry.
It describes the work requested and only the results acknowledged by Django.
"""
from .models import (
    SportsBaseDailymotionUpload,
    SportsBaseSyncJob,
    SportsBaseYouTubeUpload,
)


def _iso(value):
    return value.isoformat() if value else None


def _remaining(status):
    return {
        "pending": "À effectuer",
        "running": "Traitement en cours ; résultat non reçu",
        "success": "Aucune action restante signalée pour cette tâche",
        "uploaded": "Aucune action restante signalée pour cette publication",
        "partial": "Contrôler et compléter les éléments manquants",
        "failed": "Erreur à corriger avant une nouvelle tentative",
        "link_pending": "Ajouter le lien final de la vidéo",
    }.get(status, "Statut à vérifier")


def _observed_summary(job):
    summary = job.result_summary or {}
    evidence = []
    if summary.get("profile_updated") is True:
        evidence.append("Profil synchronisé")
    if "matches_received" in summary:
        count = summary["matches_received"]
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            evidence.append(
                f"{count} match(s) remonté(s)" if count else "Aucun nouveau match remonté"
            )
    if "reports_ready" in summary:
        count = summary["reports_ready"]
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            evidence.append(f"{count} rapport(s) préparé(s)")
    if evidence:
        return " · ".join(evidence)
    if job.status == SportsBaseSyncJob.Status.PENDING:
        return "Non commencé"
    if job.status == SportsBaseSyncJob.Status.RUNNING:
        return "En cours ; résultat non encore enregistré"
    return "Aucun détail de résultat enregistré"


def sync_job_report(job):
    """One existing SportsBase job, without inferring unrecorded actions."""
    status = job.status
    return {
        "kind": "SportsBase",
        "id": job.pk,
        "player": job.subscription.player.name,
        "planned": job.get_job_type_display(),
        "observed": _observed_summary(job),
        "remaining": _remaining(status),
        "status": status,
        "status_label": job.get_status_display(),
        "error": (job.error_message or "")[:200],
        "date": _iso(job.finished_at or job.started_at or job.created_at),
        "_sort": job.finished_at or job.started_at or job.created_at,
        "url": "",
    }


def video_upload_report(upload, provider):
    """A YouTube / Dailymotion upload is successful only with a stored URL."""
    is_youtube = provider == "YouTube"
    url = (upload.youtube_url if is_youtube else upload.dailymotion_url) or ""
    recorded_success = upload.status == "uploaded" and bool(url)
    status = upload.status if (upload.status != "uploaded" or recorded_success) else "failed"
    if recorded_success:
        observed = f"Lien {provider} enregistré"
    elif upload.status == "link_pending":
        observed = "Transfert annoncé ; lien final non enregistré"
    elif url:
        observed = "Identifiant ou lien présent ; publication non confirmée"
    elif upload.status == "pending":
        observed = "Non commencé"
    elif upload.status == "running":
        observed = "En cours ; publication non confirmée"
    else:
        observed = "Aucune publication confirmée"

    return {
        "kind": provider,
        "id": upload.pk,
        "player": upload.match.subscription.player.name,
        "planned": f"Publier All Actions du match {upload.match.sportsbase_match_id} sur {provider}",
        "observed": observed,
        "remaining": _remaining(status),
        "status": status,
        "status_label": "À vérifier" if status == "failed" and upload.status == "uploaded"
            else upload.get_status_display(),
        "error": (upload.error_message or "")[:200],
        "date": _iso(upload.finished_at or upload.started_at or upload.created_at),
        "_sort": upload.finished_at or upload.started_at or upload.created_at,
        "url": url if recorded_success else "",
    }


def recent_agent_reports(limit=25):
    """Last recorded jobs, including uploads; no session heartbeat required."""
    fetch_limit = max(1, min(int(limit), 100))
    sync_jobs = SportsBaseSyncJob.objects.select_related(
        "subscription__player"
    ).order_by("-created_at", "-pk")[:fetch_limit]
    youtube_jobs = SportsBaseYouTubeUpload.objects.select_related(
        "match__subscription__player"
    ).order_by("-created_at", "-pk")[:fetch_limit]
    dailymotion_jobs = SportsBaseDailymotionUpload.objects.select_related(
        "match__subscription__player"
    ).order_by("-created_at", "-pk")[:fetch_limit]

    results = (
        [sync_job_report(item) for item in sync_jobs]
        + [video_upload_report(item, "YouTube") for item in youtube_jobs]
        + [video_upload_report(item, "Dailymotion") for item in dailymotion_jobs]
    )
    results.sort(key=lambda item: item["_sort"], reverse=True)
    for item in results:
        del item["_sort"]
    return results[:fetch_limit]
