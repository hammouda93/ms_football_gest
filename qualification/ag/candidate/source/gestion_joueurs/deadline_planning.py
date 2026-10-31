from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from .decorators import superadmin_required
from .models import Video, VideoEditor


ACTIVE_PLANNING_STATUSES = (
    Video.StatusChoices.PENDING,
    Video.StatusChoices.IN_PROGRESS,
    Video.StatusChoices.COMPLETED_COLLAB,
)

STATUS_META = {
    Video.StatusChoices.PENDING: {
        "label": "En attente",
        "tone": "neutral",
        "weight": 0.8,
    },
    Video.StatusChoices.IN_PROGRESS: {
        "label": "En cours",
        "tone": "primary",
        "weight": 1.3,
    },
    Video.StatusChoices.COMPLETED_COLLAB: {
        "label": "Finition / classification",
        "tone": "success",
        "weight": 0.7,
    },
}

WEEKDAY_SHORT = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")
MONTH_SHORT = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)
MONTH_LONG = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _as_positive_int(raw_value):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _editor_name(editor):
    if not editor:
        return "Toute l’équipe"
    if editor.user_id and editor.user:
        return editor.user.get_full_name() or editor.user.username
    return f"Monteur #{editor.pk}"


def _video_effort(video):
    meta = STATUS_META.get(video.status, STATUS_META[Video.StatusChoices.PENDING])
    seasons = max(int(video.seasons_to_process or 1), 1)
    return round(meta["weight"] * seasons, 1)


def _load_level(score):
    if score <= 0:
        return {"tone": "free", "label": "Disponible"}
    if score <= 1.25:
        return {"tone": "light", "label": "Charge légère"}
    if score <= 2.75:
        return {"tone": "balanced", "label": "Charge équilibrée"}
    if score <= 4:
        return {"tone": "busy", "label": "Date chargée"}
    return {"tone": "saturated", "label": "Très chargée"}


def _date_label(value):
    return f"{WEEKDAY_SHORT[value.weekday()]} {value.day} {MONTH_LONG[value.month - 1]}"


def _video_payload(video):
    meta = STATUS_META.get(video.status, STATUS_META[Video.StatusChoices.PENDING])
    editor = video.editor
    return {
        "id": video.pk,
        "player": video.player.name,
        "deadline": video.deadline.isoformat(),
        "deadline_label": _date_label(video.deadline),
        "status": video.status,
        "status_label": meta["label"],
        "status_tone": meta["tone"],
        "editor": _editor_name(editor),
        "seasons": int(video.seasons_to_process or 1),
        "effort": _video_effort(video),
        "edit_url": reverse("edit_video", args=(video.pk,)),
    }


def build_deadline_planning_payload(
    *,
    selected_date=None,
    editor_id=None,
    exclude_video_id=None,
    today=None,
    calendar_days=28,
):
    """Build a read-only workload snapshot for the deadline assistant."""
    today = today or timezone.localdate()
    selected_date = selected_date or (today + timedelta(days=7))
    editor_id = _as_positive_int(editor_id)
    exclude_video_id = _as_positive_int(exclude_video_id)

    videos = Video.objects.filter(status__in=ACTIVE_PLANNING_STATUSES)
    if exclude_video_id:
        videos = videos.exclude(pk=exclude_video_id)
    videos = list(
        videos.select_related("player", "editor__user").order_by("deadline", "pk")
    )

    editor = None
    if editor_id:
        editor = VideoEditor.objects.select_related("user").filter(pk=editor_id).first()
        if editor is None:
            editor_id = None

    videos_by_date = defaultdict(list)
    for video in videos:
        if video.deadline:
            videos_by_date[video.deadline].append(video)

    def day_snapshot(day):
        day_videos = videos_by_date.get(day, [])
        editor_videos = (
            [video for video in day_videos if video.editor_id == editor_id]
            if editor_id
            else day_videos
        )
        global_score = round(sum(_video_effort(video) for video in day_videos), 1)
        editor_score = round(sum(_video_effort(video) for video in editor_videos), 1)
        reference_score = editor_score if editor_id else global_score
        load = _load_level(reference_score)
        return {
            "date": day.isoformat(),
            "date_label": _date_label(day),
            "global_count": len(day_videos),
            "editor_count": len(editor_videos),
            "global_score": global_score,
            "editor_score": editor_score,
            "tone": load["tone"],
            "load_label": load["label"],
        }

    calendar_start = today
    if selected_date >= today:
        calendar_start = max(today, selected_date - timedelta(days=7))
    calendar = []
    for offset in range(calendar_days):
        day = calendar_start + timedelta(days=offset)
        snapshot = day_snapshot(day)
        snapshot.update(
            {
                "weekday": WEEKDAY_SHORT[day.weekday()],
                "day": day.day,
                "month": MONTH_SHORT[day.month - 1],
                "is_today": day == today,
                "is_selected": day == selected_date,
            }
        )
        calendar.append(snapshot)

    period_start = selected_date - timedelta(days=2)
    period_end = selected_date + timedelta(days=2)
    period_videos = [
        video
        for video in videos
        if video.deadline and period_start <= video.deadline <= period_end
    ]
    period_editor_videos = (
        [video for video in period_videos if video.editor_id == editor_id]
        if editor_id
        else period_videos
    )

    selection = day_snapshot(selected_date)
    selection.update(
        {
            "is_past": selected_date < today,
            "days_from_today": (selected_date - today).days,
            "window_count": len(period_videos),
            "window_editor_count": len(period_editor_videos),
        }
    )

    suggestion_anchor = selected_date if selected_date >= today else today + timedelta(days=1)
    suggestion_start = max(today + timedelta(days=1), suggestion_anchor - timedelta(days=4))
    suggestion_candidates = []
    for offset in range(21):
        day = suggestion_start + timedelta(days=offset)
        if day == selected_date:
            continue
        snapshot = day_snapshot(day)
        reference_score = (
            snapshot["editor_score"] if editor_id else snapshot["global_score"]
        )
        distance = abs((day - suggestion_anchor).days)
        suggestion_candidates.append(
            (reference_score, snapshot["global_score"], distance, day, snapshot)
        )
    suggestion_candidates.sort(key=lambda item: item[:4])
    suggestions = [
        {
            **snapshot,
            "reason": (
                "Aucune vidéo planifiée"
                if snapshot["global_count"] == 0
                else (
                    f"{snapshot['global_count']} vidéo"
                    f"{'s' if snapshot['global_count'] > 1 else ''} prévue"
                    f"{'s' if snapshot['global_count'] > 1 else ''}"
                )
            ),
        }
        for _, _, _, _, snapshot in suggestion_candidates[:3]
    ]

    overdue_videos = [video for video in videos if video.deadline and video.deadline < today]
    attention_videos = sorted(
        overdue_videos,
        key=lambda video: (video.deadline, video.pk),
    )

    next_week_end = today + timedelta(days=6)
    return {
        "today": today.isoformat(),
        "selected_date": selected_date.isoformat(),
        "selected_editor": {
            "id": editor_id,
            "name": _editor_name(editor),
        },
        "selection": selection,
        "summary": {
            "active_count": len(videos),
            "overdue_count": len(overdue_videos),
            "finishing_count": sum(
                video.status == Video.StatusChoices.COMPLETED_COLLAB
                for video in videos
            ),
            "next_7_days_count": sum(
                today <= video.deadline <= next_week_end
                for video in videos
                if video.deadline
            ),
        },
        "calendar": calendar,
        "suggestions": suggestions,
        "period_videos": [_video_payload(video) for video in period_videos[:12]],
        "attention_videos": [_video_payload(video) for video in attention_videos[:6]],
        "method_note": (
            "Indice indicatif basé sur le statut et le nombre de saisons. "
            "Seules les vidéos Pending, In Progress et Completed Collab sont "
            "comptées. Il vous informe sans bloquer la date choisie."
        ),
    }


@login_required
@superadmin_required
@require_GET
def deadline_planning_assistant(request):
    raw_date = (request.GET.get("date") or "").strip()
    selected_date = parse_date(raw_date) if raw_date else None
    if raw_date and selected_date is None:
        return JsonResponse(
            {"error": "La date doit être au format AAAA-MM-JJ."},
            status=400,
        )

    payload = build_deadline_planning_payload(
        selected_date=selected_date,
        editor_id=request.GET.get("editor_id"),
        exclude_video_id=request.GET.get("exclude_video_id"),
    )
    return JsonResponse(payload)
