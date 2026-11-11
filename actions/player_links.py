"""Reviewed player-organization unlink, without deleting historical relationships.

Mirrors the portal's link deactivation logic, never sends messages or creates
client accounts. Operation targets a membership ID, not a player ID.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone

from client_portal.models import OrganizationPlayer


class PlayerOrganizationLink:
    """Add/reactivate an organization relationship without requiring a video pack."""

    model = OrganizationPlayer

    def contract(self):
        return {
            "model": self.model._meta.label,
            "fields": ["player", "organization", "label", "expected_matches"],
            "required": ["player", "organization"],
            "schema": {
                "player": {"type": "integer"},
                "organization": {"type": "integer"},
                "label": {"type": "string", "maxLength": 100},
                "expected_matches": {"type": "integer", "enum": [3, 5, 10]},
            },
            "family": "player_organization_link/v1",
            "permission": "active_superuser",
            "sourceView": "client_portal.views.organization_player_add",
            "effects": ["membership_created_or_reactivated"],
            "excludedEffects": [
                "video", "invoice", "accounts", "emails", "whatsapp",
                "jobs", "publication",
            ],
        }

    def cleaned(self, values, actor_id, lock=False):
        from client_portal.forms import OrganizationPlayerForm
        from client_portal.models import Organization
        from gestion_joueurs.models import Player

        PlayerOrganizationUnlink._authorize(actor_id)
        if not {"player", "organization"} <= set(values):
            raise ValueError("missing_field")
        if set(values) - set(self.contract()["fields"]):
            raise ValueError("field_forbidden")
        qs = Organization.objects.select_for_update() if lock else Organization.objects
        try:
            organization = qs.get(pk=values["organization"], is_active=True)
        except Organization.DoesNotExist:
            raise ValueError("organization_unavailable") from None
        player_qs = Player.objects.select_for_update() if lock else Player.objects
        try:
            player = player_qs.get(pk=values["player"])
        except Player.DoesNotExist:
            raise ValueError("player_missing") from None
        link_qs = (
            OrganizationPlayer.objects.select_for_update()
            if lock else OrganizationPlayer.objects
        )
        current = link_qs.filter(
            player=player, organization=organization,
        ).first()
        if current and current.is_active and current.ended_at is None:
            raise ValueError("link_already_active")
        form = OrganizationPlayerForm(
            data={"player": player.pk, "label": values.get("label", "")},
            organization=organization,
        )
        if not form.is_valid():
            raise ValueError("invalid_organization_player_form")
        if "expected_matches" in values and values["expected_matches"] not in (3, 5, 10):
            raise ValueError("invalid_expected_matches")
        return current, {
            "player": player,
            "organization": organization,
            "label": values.get("label", current.label if current else ""),
            "expected_matches": values.get(
                "expected_matches",
                current.expected_matches if current else None,
            ),
        }

    def preview(self, step, actor_id):
        current, cleaned = self.cleaned(step["values"], actor_id)
        return {
            "as": step["as"], "op": step["op"],
            "id": current.pk if current else None,
            "player": {
                "id": cleaned["player"].pk, "name": cleaned["player"].name,
            },
            "organization": {
                "id": cleaned["organization"].pk,
                "name": cleaned["organization"].name,
            },
            "old": None if current is None else {
                "is_active": current.is_active,
                "ended_at": current.ended_at.isoformat() if current.ended_at else None,
                "label": current.label,
                "expected_matches": current.expected_matches,
            },
            "new": {
                "is_active": True,
                "ended_at": None,
                "label": cleaned["label"],
                "expected_matches": cleaned["expected_matches"],
            },
            "contract": self.contract(),
        }

    def apply(self, values, actor_id):
        from django.contrib.auth import get_user_model

        current, cleaned = self.cleaned(values, actor_id, lock=True)
        actor = get_user_model().objects.get(pk=actor_id)
        defaults = {
            "is_active": True,
            "ended_at": None,
            "added_by": actor,
            "label": cleaned["label"],
            "expected_matches": cleaned["expected_matches"],
        }
        link, _created = OrganizationPlayer.objects.update_or_create(
            player=cleaned["player"], organization=cleaned["organization"],
            defaults=defaults,
        )
        return link


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


PLAYER_LINKS = {
    "player.organization.link": PlayerOrganizationLink(),
    "player.organization.unlink": PlayerOrganizationUnlink(),
}
