from django.contrib import admin

from .models import Prospect


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "service_type",
        "league",
        "country",
        "club",
        "status",
        "player",
        "created_at",
    )
    list_filter = (
        "status",
        "service_type",
        "position",
        "league",
        "country",
        "created_at",
    )
    search_fields = (
        "full_name",
        "whatsapp_number",
        "email",
        "club",
        "country",
        "transfermarkt_url",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
