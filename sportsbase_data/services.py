import base64
import binascii
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.template.defaultfilters import slugify
from django.utils import timezone

from .models import (
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
    SportsBaseYouTubeUpload,
)


MAX_MAP_BYTES = 5 * 1024 * 1024
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def active_subscriptions():
    today = timezone.localdate()
    return SportsBaseSubscription.objects.filter(
        is_active=True,
        starts_on__lte=today,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))


def queue_sync(subscription, *, requested_by=None, job_type=None, force=False):
    job_type = job_type or SportsBaseSyncJob.JobType.FULL
    active_job = subscription.sync_jobs.filter(
        status__in={
            SportsBaseSyncJob.Status.PENDING,
            SportsBaseSyncJob.Status.RUNNING,
        }
    ).first()
    if active_job and not force:
        return active_job, False
    job = SportsBaseSyncJob.objects.create(
        subscription=subscription,
        job_type=job_type,
        requested_by=requested_by,
    )
    subscription.last_sync_state = SportsBaseSubscription.SyncState.QUEUED
    subscription.last_error = ""
    subscription.save(update_fields=("last_sync_state", "last_error", "updated_at"))
    return job, True


def ensure_due_jobs():
    now = timezone.now()
    stale_before = now - timedelta(
        hours=getattr(settings, "SPORTSBASE_JOB_TIMEOUT_HOURS", 4)
    )
    stale_jobs = SportsBaseSyncJob.objects.filter(
        status=SportsBaseSyncJob.Status.RUNNING,
        started_at__lt=stale_before,
    ).select_related("subscription")
    for stale_job in stale_jobs:
        fail_sync_job(
            stale_job,
            "L’agent local n’a pas terminé cette tâche dans le délai prévu.",
        )
    created = 0
    for subscription in active_subscriptions().select_related("player"):
        if subscription.sync_jobs.filter(
            status__in={
                SportsBaseSyncJob.Status.PENDING,
                SportsBaseSyncJob.Status.RUNNING,
            }
        ).exists():
            continue
        if subscription.last_sync_at:
            next_due = subscription.last_sync_at + timedelta(
                hours=subscription.sync_interval_hours
            )
            if next_due > now:
                continue
        _job, was_created = queue_sync(subscription)
        created += int(was_created)
    return created


@transaction.atomic
def fail_sync_job(job, error_message):
    job = SportsBaseSyncJob.objects.select_for_update().select_related(
        "subscription"
    ).get(pk=job.pk)
    now = timezone.now()
    job.status = SportsBaseSyncJob.Status.FAILED
    job.error_message = str(error_message)
    job.finished_at = now
    job.save(update_fields=("status", "error_message", "finished_at"))
    subscription = job.subscription
    subscription.last_sync_at = now
    subscription.last_sync_state = SportsBaseSubscription.SyncState.FAILED
    subscription.last_error = str(error_message)
    subscription.save(
        update_fields=("last_sync_at", "last_sync_state", "last_error", "updated_at")
    )
    return job


def _job_payload(job):
    subscription = job.subscription
    player = subscription.player
    known_matches = []
    for match in subscription.matches.select_related("player_stats").order_by(
        "-match_date", "-sportsbase_match_id"
    ):
        try:
            stats_metadata = match.player_stats.source_metadata or {}
        except SportsBaseMatchStats.DoesNotExist:
            stats_metadata = {}
        known_matches.append(
            {
                "sportsbase_match_id": match.sportsbase_match_id,
                "sync_state": match.sync_state,
                "actions_state": match.actions_state,
                "complete": match.is_complete,
                "local_folder_key": match.local_folder_key,
                "all_actions_filename": match.all_actions_filename,
                "all_actions_downloaded_at": (
                    match.all_actions_downloaded_at.isoformat()
                    if match.all_actions_downloaded_at
                    else None
                ),
                "all_actions_emailed_at": (
                    match.all_actions_emailed_at.isoformat()
                    if match.all_actions_emailed_at
                    else None
                ),
                "delivery_error": match.delivery_error,
                "players_statistics_xlsx": stats_metadata.get(
                    "players_statistics_xlsx", ""
                ),
            }
        )
    return {
        "job_id": job.pk,
        "job_type": job.job_type,
        "subscription_id": subscription.pk,
        "season": subscription.season,
        "sync_from_date": (
            subscription.sync_from_date.isoformat()
            if subscription.sync_from_date
            else None
        ),
        "first_match_id": subscription.first_match_id,
        "all_actions_enabled": subscription.all_actions_enabled,
        "email_delivery_enabled": (
            subscription.email_delivery_enabled
            and not subscription.youtube_delivery_enabled
        ),
        "youtube_delivery_enabled": subscription.youtube_delivery_enabled,
        "player": {
            "id": player.pk,
            "name": player.name,
            "club": player.club,
            "email": player.email,
            "sportsbase_url": player.sportsbase_url,
            "storage_key": f"player_{player.pk}_{slugify(player.name) or 'joueur'}",
        },
        "known_matches": known_matches,
    }


@transaction.atomic
def claim_next_job():
    ensure_due_jobs()
    job = (
        SportsBaseSyncJob.objects.select_for_update()
        .select_related("subscription__player")
        .filter(
            status=SportsBaseSyncJob.Status.PENDING,
            subscription__in=active_subscriptions(),
        )
        .order_by("created_at")
        .first()
    )
    if not job:
        return None
    job.status = SportsBaseSyncJob.Status.RUNNING
    job.started_at = timezone.now()
    job.attempts += 1
    job.payload = _job_payload(job)
    job.save(update_fields=("status", "started_at", "attempts", "payload"))
    subscription = job.subscription
    subscription.last_sync_state = SportsBaseSubscription.SyncState.RUNNING
    subscription.last_error = ""
    subscription.save(update_fields=("last_sync_state", "last_error", "updated_at"))
    return job


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if timezone.is_naive(result):
        result = timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _decode_png(value):
    if not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Une image SportsBase reçue n’est pas un PNG base64 valide.") from exc
    if len(decoded) > MAX_MAP_BYTES:
        raise ValueError("Une image SportsBase dépasse la limite de 5 Mo.")
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Une carte SportsBase reçue n’est pas au format PNG.")
    return decoded


def _profile_defaults(profile, subscription):
    return {
        "sportsbase_player_id": str(profile.get("sportsbase_player_id") or ""),
        "sportsbase_player_name": str(profile.get("sportsbase_player_name") or "")[:160],
        "native_name": str(profile.get("native_name") or "")[:160],
        "club_name": str(profile.get("club_name") or "")[:160],
        "club_sportsbase_id": str(profile.get("club_sportsbase_id") or "")[:32],
        "profile_image_url": str(profile.get("profile_image_url") or ""),
        "date_of_birth": _parse_date(profile.get("date_of_birth")),
        "nationality": str(profile.get("nationality") or "")[:100],
        "contract_expires": _parse_date(profile.get("contract_expires")),
        "height_weight": str(profile.get("height_weight") or "")[:100],
        "national_team": str(profile.get("national_team") or "")[:160],
        "strong_foot": str(profile.get("strong_foot") or "")[:80],
        "time_on_field_percent": profile.get("time_on_field_percent") or None,
        "positions": profile.get("positions") or [],
        "season_statistics": profile.get("season_statistics") or {},
        "average_statistics": profile.get("average_statistics") or {},
        "season_table_headers": profile.get("season_table_headers") or [],
        "season_match_rows": profile.get("season_match_rows") or [],
        "radar_metrics": profile.get("radar_metrics") or [],
        "source_metadata": profile.get("source_metadata") or {},
        "synced_at": timezone.now(),
    }


def _upsert_profile(subscription, profile):
    if not profile:
        return None
    season = str(profile.get("season") or subscription.season)[:20]
    defaults = _profile_defaults(profile, subscription)
    snapshot, _created = SportsBaseSeasonSnapshot.objects.update_or_create(
        subscription=subscription,
        season=season,
        defaults=defaults,
    )
    image_fields = []
    if profile.get("radar_png_base64"):
        snapshot.radar_png = _decode_png(profile["radar_png_base64"])
        image_fields.append("radar_png")
    if profile.get("heatmap_png_base64"):
        snapshot.heatmap_png = _decode_png(profile["heatmap_png_base64"])
        image_fields.append("heatmap_png")
    if profile.get("ball_touches_png_base64"):
        snapshot.ball_touches_png = _decode_png(profile["ball_touches_png_base64"])
        image_fields.append("ball_touches_png")
    if image_fields:
        snapshot.maps_captured_at = timezone.now()
        image_fields.extend(("maps_captured_at", "updated_at"))
        snapshot.save(update_fields=tuple(image_fields))
    return snapshot


def _match_defaults(item, subscription):
    valid_sync_states = {value for value, _label in SportsBaseMatch.SyncState.choices}
    valid_action_states = {value for value, _label in SportsBaseMatch.ActionsState.choices}
    sync_state = item.get("sync_state", SportsBaseMatch.SyncState.SYNCED)
    actions_state = item.get("actions_state")
    if sync_state not in valid_sync_states:
        sync_state = SportsBaseMatch.SyncState.PARTIAL
    if actions_state not in valid_action_states:
        actions_state = (
            SportsBaseMatch.ActionsState.QUEUED
            if subscription.all_actions_enabled
            else SportsBaseMatch.ActionsState.NOT_REQUESTED
        )
    return {
        "season": str(item.get("season") or subscription.season)[:20],
        "match_date": _parse_date(item.get("match_date")),
        "competition": str(item.get("competition") or "")[:160],
        "week": str(item.get("week") or "")[:80],
        "referee": str(item.get("referee") or "")[:160],
        "home_team": str(item.get("home_team") or "")[:160],
        "home_team_id": str(item.get("home_team_id") or "")[:32],
        "away_team": str(item.get("away_team") or "")[:160],
        "away_team_id": str(item.get("away_team_id") or "")[:32],
        "home_score": item.get("home_score"),
        "away_score": item.get("away_score"),
        "lineup": str(item.get("lineup") or "")[:80],
        "match_url": str(item.get("match_url") or ""),
        "sync_state": sync_state,
        "actions_state": actions_state,
        "local_folder_key": str(item.get("local_folder_key") or "")[:255],
        "all_actions_filename": str(item.get("all_actions_filename") or "")[:255],
        "all_actions_downloaded_at": _parse_datetime(
            item.get("all_actions_downloaded_at")
        ),
        "all_actions_emailed_at": _parse_datetime(item.get("all_actions_emailed_at")),
        "delivery_error": str(item.get("delivery_error") or ""),
        "source_metadata": item.get("source_metadata") or {},
        "synced_at": timezone.now(),
    }


def _upsert_match(subscription, item):
    match_id = str(item.get("sportsbase_match_id") or "").strip()
    if not match_id or not match_id.isdigit():
        raise ValueError("Un match synchronisé ne possède pas d’identifiant SportsBase valide.")
    defaults = _match_defaults(item, subscription)
    match, _created = SportsBaseMatch.objects.update_or_create(
        subscription=subscription,
        sportsbase_match_id=match_id,
        defaults=defaults,
    )
    stats = item.get("stats")
    if stats:
        stat_defaults = {
            "team_name": str(stats.get("team_name") or "")[:160],
            "position": str(stats.get("position") or "")[:80],
            "position_percentages": stats.get("position_percentages") or [],
            "minutes_played": stats.get("minutes_played"),
            "index": stats.get("index"),
            "team_rank": stats.get("team_rank"),
            "match_rank": stats.get("match_rank"),
            "summary_statistics": stats.get("summary_statistics") or {},
            "success_rates": stats.get("success_rates") or {},
            "detailed_statistics": stats.get("detailed_statistics") or {},
            "team_table": stats.get("team_table") or [],
            "source_metadata": stats.get("source_metadata") or {},
            "synced_at": timezone.now(),
        }
        match_stats, _created = SportsBaseMatchStats.objects.update_or_create(
            match=match,
            defaults=stat_defaults,
        )
        image_fields = []
        if stats.get("heatmap_png_base64"):
            match_stats.heatmap_png = _decode_png(stats["heatmap_png_base64"])
            image_fields.append("heatmap_png")
        if stats.get("ball_touches_png_base64"):
            match_stats.ball_touches_png = _decode_png(
                stats["ball_touches_png_base64"]
            )
            image_fields.append("ball_touches_png")
        if image_fields:
            match_stats.maps_captured_at = timezone.now()
            image_fields.append("maps_captured_at")
            match_stats.save(update_fields=tuple(image_fields))
    return match


def _youtube_title(match):
    player_name = match.subscription.player.name.strip()
    fixture = f"{match.home_team.strip()} vs {match.away_team.strip()}".strip()
    match_date = match.match_date.strftime("%d-%m-%Y") if match.match_date else ""
    parts = [player_name, "All Actions", fixture, match_date]
    return " — ".join(part for part in parts if part)[:100]


def _youtube_description(match):
    lines = [
        "MS Performance — All Actions",
        f"Joueur : {match.subscription.player.name}",
        f"Rencontre : {match.home_team} {match.score} {match.away_team}",
    ]
    if match.match_date:
        lines.append(f"Date : {match.match_date.strftime('%d/%m/%Y')}")
    if match.competition:
        lines.append(f"Compétition : {match.competition}")
    return "\n".join(lines)


def ensure_youtube_upload_jobs():
    """Create one idempotent upload task for every eligible local All Actions file."""
    eligible = (
        active_subscriptions()
        .filter(youtube_delivery_enabled=True)
        .values_list("pk", flat=True)
    )
    matches = SportsBaseMatch.objects.filter(
        subscription_id__in=eligible,
        actions_state__in={
            SportsBaseMatch.ActionsState.DOWNLOADED,
            SportsBaseMatch.ActionsState.EMAILED,
        },
    ).exclude(local_folder_key="").exclude(all_actions_filename="")
    created = 0
    for match in matches.iterator():
        _upload, was_created = SportsBaseYouTubeUpload.objects.get_or_create(
            match=match,
            defaults={"upload_title": _youtube_title(match)},
        )
        created += int(was_created)
    return created


def _youtube_job_payload(upload):
    match = upload.match
    return {
        "job_id": upload.pk,
        "player": {
            "id": match.subscription.player_id,
            "name": match.subscription.player.name,
        },
        "match": {
            "id": match.pk,
            "match_id": match.sportsbase_match_id,
            "date": match.match_date.isoformat() if match.match_date else None,
            "competition": match.competition,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "score": match.score,
            "local_folder_key": match.local_folder_key,
            "filename": match.all_actions_filename,
        },
        "youtube": {
            "title": upload.upload_title or _youtube_title(match),
            "description": _youtube_description(match),
            "visibility": "unlisted",
        },
    }


@transaction.atomic
def claim_next_youtube_upload():
    ensure_youtube_upload_jobs()
    stale_before = timezone.now() - timedelta(
        hours=getattr(settings, "YOUTUBE_UPLOAD_JOB_TIMEOUT_HOURS", 6)
    )
    SportsBaseYouTubeUpload.objects.filter(
        status=SportsBaseYouTubeUpload.Status.RUNNING,
        started_at__lt=stale_before,
    ).update(
        status=SportsBaseYouTubeUpload.Status.FAILED,
        error_message="L’agent local n’a pas terminé l’upload dans le délai prévu.",
        finished_at=timezone.now(),
    )
    upload = (
        SportsBaseYouTubeUpload.objects.select_for_update()
        .select_related("match__subscription__player")
        .filter(status=SportsBaseYouTubeUpload.Status.PENDING)
        .order_by("-match__match_date", "created_at")
        .first()
    )
    if upload is None:
        return None
    upload.status = SportsBaseYouTubeUpload.Status.RUNNING
    upload.started_at = timezone.now()
    upload.finished_at = None
    upload.attempts += 1
    upload.error_message = ""
    if not upload.upload_title:
        upload.upload_title = _youtube_title(upload.match)
    upload.save(
        update_fields=(
            "status",
            "started_at",
            "finished_at",
            "attempts",
            "error_message",
            "upload_title",
            "updated_at",
        )
    )
    upload.payload = _youtube_job_payload(upload)
    return upload


def extract_youtube_video_id(value):
    if not value:
        return ""
    try:
        parsed = urlparse(str(value).strip())
    except (TypeError, ValueError):
        return ""
    host = parsed.netloc.casefold().split(":", 1)[0]
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            parts = parsed.path.strip("/").split("/")
            video_id = parts[1] if len(parts) > 1 else ""
    return video_id if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id) else ""


@transaction.atomic
def apply_youtube_upload_result(upload, result):
    upload = SportsBaseYouTubeUpload.objects.select_for_update().get(pk=upload.pk)
    if upload.status != SportsBaseYouTubeUpload.Status.RUNNING:
        raise ValueError("Cette tâche YouTube n’est plus en cours.")

    status = str(result.get("status") or "").strip()
    if status not in {
        SportsBaseYouTubeUpload.Status.UPLOADED,
        SportsBaseYouTubeUpload.Status.FAILED,
    }:
        raise ValueError("État final YouTube invalide.")

    now = timezone.now()
    upload.status = status
    upload.finished_at = now
    upload.error_message = str(result.get("error") or "")

    if status == SportsBaseYouTubeUpload.Status.UPLOADED:
        youtube_url = str(result.get("youtube_url") or "").strip()
        video_id = extract_youtube_video_id(youtube_url)
        if not video_id:
            raise ValueError("L’agent n’a pas fourni de lien YouTube valide.")
        supplied_video_id = str(result.get("youtube_video_id") or "").strip()
        if supplied_video_id and supplied_video_id != video_id:
            raise ValueError("L’identifiant et le lien YouTube ne correspondent pas.")
        content_sha256 = str(result.get("content_sha256") or "").strip().lower()
        if content_sha256 and not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
            raise ValueError("L’empreinte du fichier vidéo est invalide.")
        try:
            file_size = int(result.get("file_size_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("La taille du fichier vidéo est invalide.") from exc
        if file_size < 0:
            raise ValueError("La taille du fichier vidéo est invalide.")
        upload.youtube_url = youtube_url
        upload.youtube_video_id = video_id
        upload.content_sha256 = content_sha256
        upload.file_size_bytes = file_size or None
        upload.error_message = ""

    upload.save(
        update_fields=(
            "status",
            "youtube_url",
            "youtube_video_id",
            "content_sha256",
            "file_size_bytes",
            "error_message",
            "finished_at",
            "updated_at",
        )
    )
    return upload


@transaction.atomic
def retry_youtube_upload(upload):
    upload = SportsBaseYouTubeUpload.objects.select_for_update().get(pk=upload.pk)
    if upload.status == SportsBaseYouTubeUpload.Status.UPLOADED:
        raise ValueError("Cette vidéo est déjà disponible sur YouTube.")
    upload.status = SportsBaseYouTubeUpload.Status.PENDING
    upload.started_at = None
    upload.finished_at = None
    upload.error_message = ""
    upload.save(
        update_fields=(
            "status",
            "started_at",
            "finished_at",
            "error_message",
            "updated_at",
        )
    )
    return upload


@transaction.atomic
def apply_sync_result(job, result):
    job = SportsBaseSyncJob.objects.select_for_update().select_related(
        "subscription"
    ).get(pk=job.pk)
    if job.status != SportsBaseSyncJob.Status.RUNNING:
        raise ValueError("Cette tâche de synchronisation n’est plus en cours.")

    result_status = str(result.get("status") or SportsBaseSyncJob.Status.SUCCESS)
    if result_status not in {
        SportsBaseSyncJob.Status.SUCCESS,
        SportsBaseSyncJob.Status.PARTIAL,
        SportsBaseSyncJob.Status.FAILED,
    }:
        raise ValueError("État final de synchronisation invalide.")

    subscription = job.subscription
    snapshot = _upsert_profile(subscription, result.get("profile") or {})
    imported_matches = []
    for item in result.get("matches") or []:
        imported_matches.append(_upsert_match(subscription, item))

    if subscription.youtube_delivery_enabled:
        for imported_match in imported_matches:
            if (
                imported_match.actions_state
                in {
                    SportsBaseMatch.ActionsState.DOWNLOADED,
                    SportsBaseMatch.ActionsState.EMAILED,
                }
                and imported_match.local_folder_key
                and imported_match.all_actions_filename
            ):
                SportsBaseYouTubeUpload.objects.get_or_create(
                    match=imported_match,
                    defaults={"upload_title": _youtube_title(imported_match)},
                )

    from .reports import generate_reports_for_subscription

    generated_reports = generate_reports_for_subscription(subscription)

    now = timezone.now()
    error_message = str(result.get("error") or "")
    job.status = result_status
    job.result_summary = {
        "profile_updated": bool(snapshot),
        "matches_received": len(imported_matches),
        "match_ids": [match.sportsbase_match_id for match in imported_matches],
        "reports_ready": len(generated_reports),
        **(result.get("summary") or {}),
    }
    job.error_message = error_message
    job.finished_at = now
    job.save(
        update_fields=("status", "result_summary", "error_message", "finished_at")
    )

    subscription.last_sync_at = now
    subscription.last_sync_state = {
        SportsBaseSyncJob.Status.SUCCESS: SportsBaseSubscription.SyncState.SUCCESS,
        SportsBaseSyncJob.Status.PARTIAL: SportsBaseSubscription.SyncState.PARTIAL,
        SportsBaseSyncJob.Status.FAILED: SportsBaseSubscription.SyncState.FAILED,
    }[result_status]
    subscription.last_error = error_message
    subscription.save(
        update_fields=("last_sync_at", "last_sync_state", "last_error", "updated_at")
    )
    return job
