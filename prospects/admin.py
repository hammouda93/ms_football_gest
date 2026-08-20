from django.contrib import admin

from .models import Prospect


@admin.register(Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "service_type",
        "country",
        "club",
        "status",
        "created_at",
    )
    list_filter = ("status", "service_type", "position", "country", "created_at")
    search_fields = ("full_name", "whatsapp_number", "email", "club", "country")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
