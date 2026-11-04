import logging
from functools import wraps

import requests

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from gestion_joueurs.utils import parse_transfermarkt_player

from .forms import (
    ProspectManagementForm,
    ProspectRequestForm,
    ProspectStatusForm,
)
from .models import Prospect
from .services import (
    convert_prospect_to_player,
    map_player_league_to_prospect,
    map_player_position_to_prospect,
    validate_transfermarkt_profile_url,
)


logger = logging.getLogger(__name__)


def superuser_required(view_func):
    """Allow anonymous users to log in and reject authenticated non-admins."""

    @login_required(login_url="user_login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def request_create(request):
    form = ProspectRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("prospects:request_success")

    return render(request, "prospects/request_form.html", {"form": form})


def request_success(request):
    return render(request, "prospects/request_success.html")


@require_POST
def transfermarkt_import_preview(request):
    """Return editable preview data; never create a Prospect or Player."""
    raw_url = request.POST.get("url", "")
    try:
        url = validate_transfermarkt_profile_url(raw_url)
    except ValidationError as exc:
        return JsonResponse(
            {"success": False, "error": exc.messages[0]},
            status=400,
        )

    if not url:
        return JsonResponse(
            {"success": False, "error": "Lien Transfermarkt manquant."},
            status=400,
        )

    try:
        parsed_data = parse_transfermarkt_player(url)
    except ValueError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc)},
            status=400,
        )
    except requests.exceptions.RequestException:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Transfermarkt ne répond pas pour le moment. "
                    "Vous pouvez remplir le formulaire manuellement."
                ),
            },
            status=502,
        )
    except Exception:
        logger.exception("Unexpected Transfermarkt preview import failure")
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "L’import a rencontré une erreur. "
                    "Vous pouvez remplir le formulaire manuellement."
                ),
            },
            status=502,
        )

    if not parsed_data.get("name"):
        return JsonResponse(
            {
                "success": False,
                "error": "Impossible de récupérer le nom du joueur.",
            },
            status=400,
        )

    return JsonResponse(
        {
            "success": True,
            "player": {
                "name": parsed_data.get("name", ""),
                "date_of_birth": parsed_data.get("date_of_birth", ""),
                "club": parsed_data.get("club", ""),
                "league": map_player_league_to_prospect(
                    parsed_data.get("league")
                ),
                "position": map_player_position_to_prospect(
                    parsed_data.get("position")
                ),
                "transfermarkt_url": url,
            },
        }
    )


@superuser_required
def prospect_list(request):
    prospects = Prospect.objects.select_related("player")
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "").strip()
    valid_statuses = {value for value, _label in Prospect.Status.choices}

    if query:
        prospects = prospects.filter(
            Q(full_name__icontains=query)
            | Q(whatsapp_number__icontains=query)
            | Q(email__icontains=query)
            | Q(country__icontains=query)
            | Q(club__icontains=query)
        )

    if selected_status in valid_statuses:
        prospects = prospects.filter(status=selected_status)
    else:
        selected_status = ""

    page = Paginator(prospects, 25).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "query": query,
        "selected_status": selected_status,
        "status_choices": Prospect.Status.choices,
        "total_count": prospects.count(),
    }
    return render(request, "prospects/prospect_list.html", context)


@superuser_required
@require_POST
def prospect_status_update(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    form = ProspectStatusForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Le statut demandé n’est pas valide.")
        return redirect("prospects:prospect_list")

    prospect.status = form.cleaned_data["status"]
    prospect.save(update_fields=("status", "updated_at"))
    messages.success(
        request,
        f"Le statut de {prospect.full_name} a été mis à jour.",
    )
    return redirect("prospects:prospect_list")


@superuser_required
def prospect_edit(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    form = ProspectManagementForm(request.POST or None, instance=prospect)

    if request.method == "POST" and form.is_valid():
        prospect = form.save()
        messages.success(
            request,
            f"La demande de {prospect.full_name} a été mise à jour.",
        )
        return redirect("prospects:prospect_list")

    return render(
        request,
        "prospects/prospect_form.html",
        {"form": form, "prospect": prospect},
    )


@superuser_required
@require_POST
def prospect_delete(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    prospect_name = prospect.full_name
    prospect.delete()
    messages.success(request, f"La demande de {prospect_name} a été supprimée.")
    return redirect("prospects:prospect_list")


@superuser_required
@require_POST
def prospect_convert(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)

    with transaction.atomic():
        player, created = convert_prospect_to_player(prospect)

    action = "créé" if created else "retrouvé"
    messages.success(
        request,
        f"Le joueur {player.name} a été {action}. Complétez maintenant la vidéo.",
    )
    create_video_url = reverse("create_video_request")
    return redirect(f"{create_video_url}?player_id={player.pk}")


@superuser_required
@require_POST
def prospect_whatsapp_start(request, pk):
    prospect = get_object_or_404(Prospect, pk=pk)
    if prospect.status == Prospect.Status.NEW:
        prospect.status = Prospect.Status.CONTACTED
        prospect.save(update_fields=("status", "updated_at"))
    return redirect(prospect.whatsapp_url)
