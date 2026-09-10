from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AutomationEvent, AutomationRun, Video

MAX_EVENTS_PER_RUN = 6


PIPELINE_STAGE_PERCENT = {
    AutomationRun.PipelineChoices.INTRO: {
        AutomationRun.StageChoices.QUEUED: 0,
        AutomationRun.StageChoices.TRANSFERMARKT: 15,
        AutomationRun.StageChoices.CHATGPT_IMAGE: 45,
        AutomationRun.StageChoices.KLING_VIDEO: 75,
        AutomationRun.StageChoices.COMPLETED: 100,
    },
    AutomationRun.PipelineChoices.HIGHLIGHTS: {
        AutomationRun.StageChoices.QUEUED: 0,
        AutomationRun.StageChoices.SPORTSBASE_DISCOVERY: 10,
        AutomationRun.StageChoices.SPORTSBASE_GENERATION: 25,
        AutomationRun.StageChoices.SPORTSBASE_DOWNLOAD: 55,
        AutomationRun.StageChoices.PREMIERE_PROJECT: 70,
        AutomationRun.StageChoices.HUMAN_REVIEW: 78,
        AutomationRun.StageChoices.PREMIERE_FINAL: 85,
        AutomationRun.StageChoices.EXPORT: 92,
        AutomationRun.StageChoices.EXPORT_VALIDATION: 97,
        AutomationRun.StageChoices.COMPLETED: 100,
    },
    AutomationRun.PipelineChoices.DELIVERY: {
        AutomationRun.StageChoices.QUEUED: 0,
        AutomationRun.StageChoices.YOUTUBE_UPLOAD: 35,
        AutomationRun.StageChoices.YOUTUBE_VALIDATION: 70,
        AutomationRun.StageChoices.DELIVERY_UPDATE: 85,
        AutomationRun.StageChoices.WHATSAPP: 95,
        AutomationRun.StageChoices.COMPLETED: 100,
    },
}


def default_percent(pipeline: str, stage: str) -> int:
    return PIPELINE_STAGE_PERCENT.get(pipeline, {}).get(stage, 0)


def _bounded_percent(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def _event_already_recorded(run, *, stage, state, progress_percent, message):
    """Avoid recording the same polling state again and again."""
    return run.events.filter(
        stage=stage,
        state=state,
        progress_percent=progress_percent,
        message=message,
    ).exists()


def _prune_events(run, *, keep=MAX_EVENTS_PER_RUN):
    """Keep a short operational timeline; the current state lives on the run."""
    stale_ids = list(
        run.events.order_by('-created_at', '-pk')
        .values_list('pk', flat=True)[keep:]
    )
    if stale_ids:
        run.events.filter(pk__in=stale_ids).delete()


def get_or_create_active_run(video, pipeline):
    """Return the single active run, safely handling concurrent creation."""
    with transaction.atomic():
        run = (
            AutomationRun.objects.select_for_update()
            .filter(video=video, pipeline=pipeline, is_active=True)
            .first()
        )
        if run:
            return run, False

        try:
            # The savepoint keeps the outer transaction usable if another
            # worker wins the conditional-unique race at this exact moment.
            with transaction.atomic():
                run = AutomationRun.objects.create(video=video, pipeline=pipeline)
            return run, True
        except IntegrityError:
            run = AutomationRun.objects.select_for_update().get(
                video=video,
                pipeline=pipeline,
                is_active=True,
            )
            return run, False


@transaction.atomic
def report_progress(
    video,
    *,
    pipeline,
    stage,
    state=AutomationRun.StateChoices.RUNNING,
    progress_current=None,
    progress_total=None,
    progress_percent=None,
    message='',
    error_code='',
    error_detail='',
    artifacts=None,
    details=None,
    claimed_by='',
    claim_token='',
    force_event=False,
):
    run, _created = get_or_create_active_run(video, pipeline)
    if claim_token and claim_token != run.claim_token:
        raise ValueError("Cette tâche a été reprise par un autre agent.")

    if progress_current is not None:
        run.progress_current = max(0, int(progress_current))
    if progress_total is not None:
        run.progress_total = max(0, int(progress_total))

    if progress_percent is None:
        if run.progress_total > 0 and progress_current is not None:
            stage_start = default_percent(pipeline, stage)
            ratio = min(1.0, run.progress_current / run.progress_total)
            progress_percent = stage_start + round(ratio * 10)
        else:
            progress_percent = default_percent(pipeline, stage)
    progress_percent = _bounded_percent(progress_percent)

    now = timezone.now()
    run.current_stage = stage
    run.state = state
    run.progress_percent = progress_percent
    run.message = str(message or '')[:500]
    run.error_code = str(error_code or '')[:80]
    run.error_detail = str(error_detail or '')
    run.last_heartbeat_at = now
    if claimed_by:
        run.claimed_by = str(claimed_by)[:120]
    if run.started_at is None and state != AutomationRun.StateChoices.QUEUED:
        run.started_at = now

    if artifacts:
        merged_artifacts = dict(run.artifacts or {})
        merged_artifacts.update(artifacts)
        run.artifacts = merged_artifacts

    if state in {
        AutomationRun.StateChoices.SUCCEEDED,
        AutomationRun.StateChoices.FAILED,
        AutomationRun.StateChoices.CANCELLED,
    }:
        run.finished_at = now
        run.claim_token = ''
        run.claimed_by = ''
    elif state == AutomationRun.StateChoices.WAITING_EXTERNAL:
        run.claim_token = ''
        run.claimed_by = ''
        run.finished_at = None
    else:
        run.finished_at = None

    run.save()
    if force_event or not _event_already_recorded(
        run,
        stage=stage,
        state=state,
        progress_percent=progress_percent,
        message=run.message,
    ):
        AutomationEvent.objects.create(
            run=run,
            stage=stage,
            state=state,
            progress_percent=progress_percent,
            message=run.message,
            details=details or {},
        )
    _prune_events(run)
    return run


def serialize_run(run, *, include_events=False):
    if not run:
        return None
    payload = {
        'id': run.pk,
        'pipeline': run.pipeline,
        'pipeline_label': run.get_pipeline_display(),
        'state': run.state,
        'state_label': run.get_state_display(),
        'stage': run.current_stage,
        'stage_label': run.get_current_stage_display(),
        'progress_current': run.progress_current,
        'progress_total': run.progress_total,
        'progress_percent': run.progress_percent,
        'message': run.message,
        'error_code': run.error_code,
        'error_detail': run.error_detail,
        'artifacts': run.artifacts or {},
        'attempt_count': run.attempt_count,
        'claimed_by': run.claimed_by,
        'last_heartbeat_at': (
            run.last_heartbeat_at.isoformat() if run.last_heartbeat_at else None
        ),
        'started_at': run.started_at.isoformat() if run.started_at else None,
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'updated_at': run.updated_at.isoformat(),
    }
    if include_events:
        payload['events'] = [
            {
                'id': event.pk,
                'stage': event.stage,
                'stage_label': event.get_stage_display(),
                'state': event.state,
                'state_label': event.get_state_display(),
                'progress_percent': event.progress_percent,
                'message': event.message,
                'details': event.details or {},
                'created_at': event.created_at.isoformat(),
            }
            for event in run.events.all()[:MAX_EVENTS_PER_RUN]
        ]
    return payload


def attach_progress_to_videos(videos):
    videos = list(videos)
    video_ids = [video.pk for video in videos]
    runs = AutomationRun.objects.filter(
        video_id__in=video_ids,
        is_active=True,
    )
    grouped = {video_id: [] for video_id in video_ids}
    for run in runs:
        grouped.setdefault(run.video_id, []).append(run)

    pipeline_order = {
        AutomationRun.PipelineChoices.INTRO: 0,
        AutomationRun.PipelineChoices.HIGHLIGHTS: 1,
        AutomationRun.PipelineChoices.DELIVERY: 2,
    }
    for video in videos:
        video.automation_progress_runs = sorted(
            grouped.get(video.pk, []),
            key=lambda item: pipeline_order.get(item.pipeline, 99),
        )
        failed = next(
            (
                item
                for item in video.automation_progress_runs
                if item.state == AutomationRun.StateChoices.FAILED
            ),
            None,
        )
        active = next(
            (
                item
                for item in reversed(video.automation_progress_runs)
                if item.state != AutomationRun.StateChoices.SUCCEEDED
            ),
            None,
        )
        video.automation_progress = failed or active or (
            video.automation_progress_runs[-1]
            if video.automation_progress_runs
            else None
        )
    return videos


def video_payload(video, request=None):
    return {
        'video_id': video.id,
        'status': video.status,
        'processing_mode': video.processing_mode,
        'delivery_mode': video.delivery_mode,
        'automation_started': video.automation_started,
        'automation_completed': video.automation_completed,
        'delivery_automation_started': video.delivery_automation_started,
        'delivery_automation_completed': video.delivery_automation_completed,
        'intro_automation_started': video.intro_automation_started,
        'intro_automation_completed': video.intro_automation_completed,
        'intro_photo_url': (
            request.build_absolute_uri(video.intro_photo.url)
            if request and video.intro_photo
            else None
        ),
        'intro_automation_enabled': video.intro_automation_enabled,
        'season': video.season,
        'seasons_to_process': video.seasons_to_process,
        'club': video.club,
        'league': video.league,
        'deadline': video.deadline.isoformat() if video.deadline else None,
        'player': {
            'id': video.player.id,
            'name': video.player.name,
            'club': video.player.club,
            'whatsapp_number': video.player.whatsapp_number,
            'sportsbase_url': video.player.sportsbase_url,
            'transfermarkt_url': video.player.transfermarkt_url,
        },
        'editor': {
            'id': video.editor.id,
            'username': (
                video.editor.user.username
                if video.editor and video.editor.user
                else None
            ),
        },
    }


def _candidate_queryset(pipeline):
    base = Video.objects.select_related('player', 'editor__user')
    if pipeline == AutomationRun.PipelineChoices.INTRO:
        return base.filter(
            status=Video.StatusChoices.IN_PROGRESS,
            intro_automation_enabled=True,
            intro_automation_completed=False,
        )
    if pipeline == AutomationRun.PipelineChoices.HIGHLIGHTS:
        return base.filter(
            status=Video.StatusChoices.IN_PROGRESS,
            processing_mode=Video.AutomationModeChoices.AUTOMATION,
            automation_completed=False,
        )
    if pipeline == AutomationRun.PipelineChoices.DELIVERY:
        return base.filter(
            status=Video.StatusChoices.COMPLETED,
            delivery_mode=Video.AutomationModeChoices.AUTOMATION,
            delivery_automation_completed=False,
        )
    return base.none()


@transaction.atomic
def claim_next_job(
    *,
    pipeline,
    worker_id,
    stale_after_minutes=20,
    external_recheck_seconds=30,
):
    """Atomically claim one video so two desktop agents cannot process it."""
    stale_before = timezone.now() - timedelta(minutes=stale_after_minutes)
    external_recheck_before = timezone.now() - timedelta(
        seconds=external_recheck_seconds
    )
    # Lock only the Video row. ``editor__user`` is nullable and PostgreSQL
    # rejects FOR UPDATE when it is applied to the nullable side of the
    # select_related outer join.
    candidates = _candidate_queryset(pipeline).select_for_update(
        of=('self',),
    ).order_by('deadline', 'video_creation_date', 'pk')
    for video in candidates[:100]:
        run, _created = get_or_create_active_run(video, pipeline)
        busy = (
            run.state == AutomationRun.StateChoices.RUNNING
            and run.last_heartbeat_at
            and run.last_heartbeat_at >= stale_before
            and run.claimed_by
        )
        waiting_for_whatsapp = (
            pipeline == AutomationRun.PipelineChoices.DELIVERY
            and run.state == AutomationRun.StateChoices.WAITING_EXTERNAL
            and run.current_stage == AutomationRun.StageChoices.WHATSAPP
        )
        waiting_external_recently_checked = (
            run.state == AutomationRun.StateChoices.WAITING_EXTERNAL
            and run.last_heartbeat_at
            and run.last_heartbeat_at >= external_recheck_before
        )
        if busy or waiting_for_whatsapp or waiting_external_recently_checked or run.state in {
            AutomationRun.StateChoices.FAILED,
            AutomationRun.StateChoices.SUCCEEDED,
            AutomationRun.StateChoices.CANCELLED,
        }:
            continue

        previous_state = run.state
        run.state = AutomationRun.StateChoices.RUNNING
        run.claimed_by = str(worker_id)[:120]
        run.claim_token = secrets.token_hex(24)
        run.claimed_at = timezone.now()
        run.last_heartbeat_at = run.claimed_at
        run.started_at = run.started_at or run.claimed_at
        run.finished_at = None
        if previous_state != AutomationRun.StateChoices.WAITING_EXTERNAL:
            run.attempt_count += 1
        run.save()
        if (
            previous_state != AutomationRun.StateChoices.WAITING_EXTERNAL
            and not _event_already_recorded(
                run,
                stage=run.current_stage,
                state=run.state,
                progress_percent=run.progress_percent,
                message=f"Tâche prise en charge par {worker_id}",
            )
        ):
            AutomationEvent.objects.create(
                run=run,
                stage=run.current_stage,
                state=run.state,
                progress_percent=run.progress_percent,
                message=f"Tâche prise en charge par {worker_id}",
            )
        _prune_events(run)
        return video, run
    return None, None


@transaction.atomic
def retry_run(run):
    run = AutomationRun.objects.select_for_update().get(pk=run.pk)
    run.state = AutomationRun.StateChoices.QUEUED
    run.error_code = ''
    run.error_detail = ''
    run.message = 'Reprise demandée depuis l’application'
    run.claimed_by = ''
    run.claim_token = ''
    run.claimed_at = None
    run.last_heartbeat_at = None
    run.finished_at = None
    run.save()
    AutomationEvent.objects.create(
        run=run,
        stage=run.current_stage,
        state=run.state,
        progress_percent=run.progress_percent,
        message=run.message,
    )
    _prune_events(run)
    return run
