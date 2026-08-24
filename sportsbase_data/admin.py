from django.contrib import admin

from .models import (
    SportsBaseMatch,
    SportsBaseMatchStats,
    SportsBaseSeasonSnapshot,
    SportsBaseSubscription,
    SportsBaseSyncJob,
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
