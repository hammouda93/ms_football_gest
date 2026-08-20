from django.contrib import admin

from .models import (
    AgentPlayerRequest,
    CommunicationLog,
    MediaSubmission,
    Organization,
    OrganizationMembership,
    OrganizationPlayer,
    PaymentRequest,
    PlayerAccess,
    PortalAccessLink,
    PortalProfile,
    RevisionRequest,
    VideoActivity,
    VideoVersion,
    VideoWorkflow,
)


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 0


class OrganizationPlayerInline(admin.TabularInline):
    model = OrganizationPlayer
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "country", "is_active", "created_at")
    list_filter = ("kind", "is_active", "country")
    search_fields = ("name", "contact_name", "email", "whatsapp_number")
    inlines = (OrganizationMembershipInline, OrganizationPlayerInline)


@admin.register(PortalProfile)
class PortalProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "account_type", "user", "is_active")
    list_filter = ("account_type", "is_active", "preferred_language")
    search_fields = ("display_name", "user__email", "whatsapp_number")
    autocomplete_fields = ("user",)


@admin.register(VideoWorkflow)
class VideoWorkflowAdmin(admin.ModelAdmin):
    list_display = ("video", "stage", "priority", "progress", "updated_at")
    list_filter = ("stage", "priority")
    search_fields = ("video__player__name", "next_action", "blocked_reason")


@admin.register(VideoVersion)
class VideoVersionAdmin(admin.ModelAdmin):
    list_display = ("video", "version_number", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("video__player__name", "title")


@admin.register(RevisionRequest)
class RevisionRequestAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "timecode_seconds", "created_at")
    list_filter = ("status",)
    search_fields = ("version__video__player__name", "comment")


@admin.register(MediaSubmission)
class MediaSubmissionAdmin(admin.ModelAdmin):
    list_display = ("title", "video", "category", "status", "created_at")
    list_filter = ("category", "status")
    search_fields = ("title", "video__player__name", "source_url")


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ("label", "video", "amount", "status", "due_date")
    list_filter = ("status",)
    search_fields = ("label", "video__player__name")


@admin.register(AgentPlayerRequest)
class AgentPlayerRequestAdmin(admin.ModelAdmin):
    list_display = ("full_name", "organization", "status", "linked_player", "created_at")
    list_filter = ("status", "organization")
    search_fields = ("full_name", "club", "transfermarkt_url")


admin.site.register(PlayerAccess)
admin.site.register(PortalAccessLink)
admin.site.register(VideoActivity)
admin.site.register(CommunicationLog)
