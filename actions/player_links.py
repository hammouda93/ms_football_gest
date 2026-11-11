"""Reviewed player-organization unlink, without deleting historical relationships.

Mirrors the portal's link deactivation logic, never sends messages or creates
client accounts. Operation targets a membership ID, not a player ID.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from client_portal.models import OrganizationPlayer


class PlayerOrganizationUnlink:
    model = OrganizationPlayer

    @staticmethod
    def _authorize(actor_id):
        if not get_user_model().objects.filter(
            pk=actor_id, is_active=True, is_superuser=True
        ).exists():
            raise PermissionError("permission_denied")

    def target(self, pk, actor_id, lock=False):
        self._authorize(actor_id)
        qs = (
            OrganizationPlayer.objects.select_for_update()
            if lock else OrganizationPlayer.objects
        )
        try:
            link = qs.select_related("player", "organization").get(pk=pk)
        except OrganizationPlayer.DoesNotExist:
            raise ValueError("target_missing") from None
        if not link.is_active or link.ended_at is not None:
            raise ValueError("link_already_closed")
        return link

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["id"],
            "required": ["id"],
            "schema": {
                "id": {
                    "type": "integer",
                    "label": "Identifiant de l'association joueur / organisation",
                },
            },
            "family": "player_organization_unlink/v1",
            "permission": "active_superuser",
            "sourceView": "client_portal.views.organization_player_remove",
            "effects": ["membership_deactivated", "relationship_end_timestamp"],
            "excludedEffects": [
                "player_deletion", "organization_deletion", "historic_video_changes",
                "client_accounts", "emails", "whatsapp", "publication",
            ],
        }

    def cleaned(self, values, actor_id, lock=False):
        if set(values) != {"id"}:
            raise ValueError("field_forbidden")
        obj = self.target(values["id"], actor_id, lock=lock)
        return obj, {}

    def preview(self, step, actor_id):
        link, _ = self.cleaned(step["values"], actor_id)
        return {
            "as": step["as"],
            "op": step["op"],
            "id": link.pk,
            "player": {"id": link.player_id, "name": link.player.name},
            "organization": {"id": link.organization_id, "name": link.organization.name},
            "old": {
                "is_active": link.is_active,
                "ended_at": None,
            },
            "new": {
                "is_active": False,
                "ended_at": "set_at_execution",
            },
            "contract": self.contract(),
        }

    def lookup(self, prefix, limit, actor_id):
        self._authorize(actor_id)
        qs = (
            OrganizationPlayer.objects.filter(
                is_active=True,
                ended_at__isnull=True,
                player__name__istartswith=prefix,
            )
            .select_related("player", "organization")
            .order_by("player__name", "organization__name", "pk")
        )
        items = list(qs[:limit + 1])
        return {
            "rows": [
                {
                    "id": link.pk,
                    "label": (
                        f"{link.player.name} — {link.organization.name} "
                        f"(association #{link.pk})"
                    ),
                }
                for link in items[:limit]
            ],
            "hasMore": len(items) > limit,
            "limit": limit,
        }

    def apply(self, values, actor_id):
        link, _ = self.cleaned(values, actor_id, lock=True)
        link.is_active = False
        link.ended_at = timezone.now()
        link.save(update_fields=["is_active", "ended_at"])
        return link


PLAYER_LINKS = {"player.organization.unlink": PlayerOrganizationUnlink()}
