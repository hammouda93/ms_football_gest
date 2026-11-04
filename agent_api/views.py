import json
from functools import wraps

from django.core.exceptions import FieldDoesNotExist, FieldError, ObjectDoesNotExist, ValidationError
from django.db.utils import DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from . import actions, data
from .models import AgentAction


def owner_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication_required", "message": "Connexion MS Football nécessaire."}, status=401)
        if not request.user.is_active or not request.user.is_superuser:
            return JsonResponse({"error": "permission_denied", "message": "Cet accès complet exige un compte superadministrateur."}, status=403)
        try:
            response = view(request, *args, **kwargs)
        except (ValueError, TypeError, FieldDoesNotExist, FieldError, ValidationError) as error:
            response = JsonResponse({"error": "invalid_request", "message": str(error)[:1800]}, status=400)
        except ObjectDoesNotExist:
            response = JsonResponse({"error": "not_found", "message": "L’élément demandé n’existe pas."}, status=404)
        except DatabaseError:
            response = JsonResponse({"error": "database_error", "message": "La consultation n’a pas pu être traitée par la base."}, status=400)
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    return wrapped


def payload(request):
    if not request.content_type == "application/json" or len(request.body) > 100_000:
        raise ValueError("Demande JSON invalide ou trop volumineuse.")
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise ValueError("La demande doit être un objet JSON.")
    return value


@owner_only
@require_GET
def catalog(request):
    return JsonResponse({"version": 1, "database": data.catalog(), "actions": actions.catalog(), "access": "superadministrator", "serverTime": __import__("django.utils.timezone", fromlist=["now"]).now().isoformat()})


@owner_only
@require_GET
def describe(request):
    return JsonResponse(data.describe(request.GET.get("entity")))


@owner_only
@require_POST
def query(request):
    return JsonResponse(data.query(payload(request)))


@owner_only
@require_POST
def action_describe(request):
    value = payload(request)
    return JsonResponse(actions.describe(request, value.get("action"), value.get("parameters", {})))


@owner_only
@require_POST
def action_prepare(request):
    value = payload(request)
    return JsonResponse(actions.prepare(request, value.get("action"), value.get("parameters", {}), value.get("changes", {})))


@owner_only
@require_POST
def action_confirm(request):
    value = payload(request)
    if value.get("confirmation") is not True and value.get("cancel") is not True:
        raise ValueError("La proposition doit être explicitement confirmée ou annulée.")
    return JsonResponse(actions.confirm(request, value.get("planId"), value.get("secureInputs"), cancel=value.get("cancel") is True))


@owner_only
@require_GET
def action_receipt(request):
    plan = AgentAction.objects.get(pk=request.GET.get("planId"), owner=request.user)
    return JsonResponse(plan.result or {"status": plan.status, "planId": str(plan.pk), "message": "Cette action n’a pas encore de résultat final."})
