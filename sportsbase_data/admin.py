from django.contrib import admin

from .models import (
    PerformanceReport,
    PerformanceSubscriptionPayment,
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
    SportsBaseYouTubeUpload,
)


@admin.register(SportsBaseSubscription)
class SportsBaseSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "season",
        "is_active",
        "last_sync_state",
        "last_sync_at",
    )
    list_filter = ("is_active", "last_sync_state", "season")
    search_fields = ("player__name", "player__club", "player__sportsbase_url")


@admin.register(PerformanceSubscriptionPayment)
class PerformanceSubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "amount",
        "payment_date",
        "payment_method",
        "reference",
    )
    list_filter = ("payment_method", "payment_date")
    search_fields = (
        "subscription__player__name",
        "reference",
    )


@admin.register(SportsBaseSeasonSnapshot)
class SportsBaseSeasonSnapshotAdmin(admin.ModelAdmin):
    list_display = ("subscription", "season", "club_name", "synced_at")
    search_fields = ("subscription__player__name", "sportsbase_player_name")
    readonly_fields = ("radar_png", "heatmap_png", "ball_touches_png")


@admin.register(SportsBaseMatch)
class SportsBaseMatchAdmin(admin.ModelAdmin):
    list_display = (
        "sportsbase_match_id",
        "subscription",
        "match_date",
        "sync_state",
        "actions_state",
    )
    list_filter = ("sync_state", "actions_state", "season")
    search_fields = (
        "subscription__player__name",
        "home_team",
        "away_team",
        "sportsbase_match_id",
    )


@admin.register(SportsBaseMatchStats)
class SportsBaseMatchStatsAdmin(admin.ModelAdmin):
    list_display = ("match", "index", "team_rank", "match_rank", "synced_at")
    readonly_fields = ("heatmap_png", "ball_touches_png")


@admin.register(SportsBaseSyncJob)
class SportsBaseSyncJobAdmin(admin.ModelAdmin):
    list_display = ("subscription", "job_type", "status", "attempts", "created_at")
    list_filter = ("status", "job_type")
    search_fields = ("subscription__player__name",)
    readonly_fields = ("payload", "result_summary")


@admin.register(SportsBaseYouTubeUpload)
class SportsBaseYouTubeUploadAdmin(admin.ModelAdmin):
    list_display = (
        "match",
        "status",
        "attempts",
        "youtube_video_id",
        "finished_at",
    )
    list_filter = ("status",)
    search_fields = (
        "match__subscription__player__name",
        "match__home_team",
        "match__away_team",
        "youtube_video_id",
    )
    readonly_fields = (
        "content_sha256",
        "file_size_bytes",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    )


@admin.register(PerformanceReport)
class PerformanceReportAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "subscription",
        "report_type",
        "language",
        "status",
        "updated_at",
    )
    list_filter = ("report_type", "language", "status", "is_manually_edited")
    search_fields = ("title", "subscription__player__name")
    readonly_fields = ("metrics", "match_ids", "generated_at", "created_at", "updated_at")
