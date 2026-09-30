import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.contrib import messages
from django.contrib.messages.storage.base import BaseStorage
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import QueryDict
from django.urls import resolve, reverse
from django.utils import timezone

from .data import SECRET, get_model, scrub
from .models import AgentAction


@dataclass(frozen=True)
class ActionSpec:
    label: str
    entity: str = ""
    key: str = ""
    form_route: str = ""
    fields: tuple = ()
    encoding: str = "form"
    effects: str = "Modification des données par le site."


# Every write calls the existing view. No direct ORM writes to business records.
ACTIONS = {
    "edit_player": ActionSpec("Modifier un joueur", "gestion_joueurs.player", "player_id"),
    "edit_video": ActionSpec("Modifier une vidéo", "gestion_joueurs.video", "video_id", effects="La modification peut produire un historique, ajuster la facture et préparer une notification WhatsApp."),
    "create_video_request": ActionSpec("Créer une demande de vidéo", effects="Crée les données joueur/vidéo, la facturation et les notifications prévues par le site."),
    "record_payment": ActionSpec("Enregistrer un paiement", "gestion_joueurs.video", "video_id", effects="Enregistrement comptable : met à jour la facture et son solde. Ce n’est pas un virement bancaire."),
    "create_invoice": ActionSpec("Créer une facture"),
    "add_expense": ActionSpec("Enregistrer une dépense ou un salaire", effects="Peut créer un salaire et modifier son état de paiement sur la vidéo."),
    "edit_expense": ActionSpec("Modifier une dépense", "gestion_joueurs.expense", "expense_id"),
    "add_non_video_income": ActionSpec("Ajouter un revenu hors vidéo"),
    "edit_non_video_income": ActionSpec("Modifier un revenu hors vidéo", "gestion_joueurs.nonvideoincome", "pk"),
    "add_notification": ActionSpec("Créer une notification", effects="Crée une notification pour le destinataire choisi."),
    "register_video_editor": ActionSpec("Créer un compte monteur", effects="Crée un compte utilisateur et son profil de monteur."),
    "mark_notification_as_read": ActionSpec("Marquer une notification comme lue", "gestion_joueurs.notification", "notification_id", fields=()),
    "portal:organization_create": ActionSpec("Créer une organisation"),
    "portal:organization_player_add": ActionSpec("Associer un joueur à une organisation", "client_portal.organization", "pk", "portal:organization_detail"),
    "portal:organization_player_remove": ActionSpec("Retirer un joueur d’une organisation", "client_portal.organizationplayer", "link_id", fields=()),
    "portal:account_create": ActionSpec("Créer un compte portail", effects="Crée un compte et les accès joueur/organisation demandés."),
    "portal:account_edit": ActionSpec("Modifier un compte portail", "client_portal.portalprofile", "profile_id"),
    "portal:account_toggle": ActionSpec("Activer ou désactiver un compte portail", "client_portal.portalprofile", "profile_id", fields=("action",)),
    "portal:agent_request_review": ActionSpec("Traiter une demande de joueur d’un agent", "client_portal.agentplayerrequest", "request_id", fields=("decision", "player_id")),
    "portal:production_workflow_update": ActionSpec("Modifier le workflow de production", "gestion_joueurs.video", "video_id", "portal:production_video"),
    "portal:production_video_status_update": ActionSpec("Changer le statut d’une vidéo", "gestion_joueurs.video", "video_id", "portal:production_video", effects="Change le statut avec historique et effets de notification du site."),
    "portal:production_activity_add": ActionSpec("Ajouter une note ou activité à une vidéo", "gestion_joueurs.video", "video_id", "portal:production_video"),
    "portal:production_version_add": ActionSpec("Ajouter une version vidéo", "gestion_joueurs.video", "video_id", "portal:production_video"),
    "portal:production_payment_request_add": ActionSpec("Créer une demande de paiement", "gestion_joueurs.video", "video_id", "portal:production_video"),
    "portal:production_revision_resolve": ActionSpec("Résoudre une demande de révision", "client_portal.revisionrequest", "revision_id", fields=("status", "staff_response")),
    "prospects:prospect_edit": ActionSpec("Modifier un prospect", "prospects.prospect", "pk"),
    "prospects:prospect_delete": ActionSpec("Supprimer un prospect", "prospects.prospect", "pk", fields=(), effects="Supprime le prospect sélectionné."),
    "prospects:prospect_convert": ActionSpec("Convertir un prospect en joueur", "prospects.prospect", "pk"),
    "prospects:prospect_status_update": ActionSpec("Changer le statut d’un prospect", "prospects.prospect", "pk", fields=("status",)),
    "performance:subscription_create": ActionSpec("Créer un abonnement performance"),
    "performance:subscription_edit": ActionSpec("Modifier un abonnement performance", "sportsbase_data.sportsbasesubscription", "pk"),
    "performance:subscription_payment_add": ActionSpec("Enregistrer un paiement d’abonnement", "sportsbase_data.sportsbasesubscription", "pk", effects="Ajoute un paiement comptable à l’abonnement."),
    "performance:subscription_toggle": ActionSpec("Activer ou désactiver un abonnement", "sportsbase_data.sportsbasesubscription", "pk", fields=("action",)),
    "performance:subscription_sync": ActionSpec("Synchroniser les données SportsBase", "sportsbase_data.sportsbasesubscription", "pk", fields=("job_type",), effects="Ajoute un travail de synchronisation exécuté par le worker SportsBase."),
    "performance:youtube_upload_retry": ActionSpec("Relancer une publication YouTube", "sportsbase_data.sportsbaseyoutubeupload", "pk", fields=(), effects="Relance une publication externe YouTube."),
    "performance:dailymotion_upload_request": ActionSpec("Demander une publication Dailymotion", "sportsbase_data.sportsbasematch", "match_pk", fields=(), effects="Ajoute une demande de publication externe Dailymotion."),
    "performance:dailymotion_link_save": ActionSpec("Enregistrer un lien Dailymotion", "sportsbase_data.sportsbasematch", "match_pk", fields=("dailymotion_url",)),
    "performance:report_edit": ActionSpec("Modifier un rapport de performance", "sportsbase_data.performancereport", "pk"),
    "retry_automation_progress": ActionSpec("Relancer un pipeline de production", "gestion_joueurs.video", "video_id", fields=(), effects="Ajoute une relance de production pour le pipeline choisi."),
}


def catalog():
    result = []
    for name, spec in ACTIONS.items():
        # Reverse converters expose the actual required route parameters.
        entries = __import__("django.urls", fromlist=["get_resolver"]).get_resolver().reverse_dict.getlist(name) if ":" not in name else []
        parameters = []
        if entries:
            parameters = entries[0][0][0][1]
        elif spec.key:
            parameters = [spec.key]
        if name == "portal:organization_player_remove":
            parameters = ["pk", "link_id"]
        if name == "retry_automation_progress":
            parameters = ["video_id", "pipeline"]
        result.append({"action": name, "label": spec.label, "parameters": parameters, "effects": spec.effects, "requiresReview": True})
    return result


def validate(name, parameters):
    if name not in ACTIONS or not isinstance(parameters, dict):
        raise ValueError("Cette action n’est pas disponible.")
    metadata = next(item for item in catalog() if item["action"] == name)
    if set(parameters) != set(metadata["parameters"]):
        raise ValueError("Les identifiants nécessaires à cette action sont incomplets.")
    for key, value in parameters.items():
        if key == "pipeline":
            if value not in {"intro", "highlights", "delivery"}:
                raise ValueError("Pipeline invalide.")
        elif type(value) is not int or value < 1:
            raise ValueError("Identifiant invalide.")
    path = reverse(name, kwargs=parameters)
    return ACTIONS[name], path


class ActionMessages(BaseStorage):
    """Only notices generated by this view count as execution evidence."""
    def _get(self, *args, **kwargs):
        return [], True

    def _store(self, messages, response, *args, **kwargs):
        return []


def clone_request(request, path, method="GET", values=None):
    nested = copy.copy(request)
    nested.method = method
    nested.path = nested.path_info = path
    nested.META = {**request.META, "REQUEST_METHOD": method, "PATH_INFO": path}
    nested._body = b""
    nested.GET = QueryDict("")
    nested._post = QueryDict("", mutable=True)
    for key, value in (values or {}).items():
        if value is True:
            nested._post[key] = "on"
        elif value is not False and value is not None:
            nested._post.setlist(key, [str(item) for item in value] if isinstance(value, list) else [str(value)])
    nested._files = {}
    nested._messages = ActionMessages(nested)
    return nested


def dispatch(request, path, method="GET", values=None):
    nested = clone_request(request, path, method, values)
    match = resolve(path)
    nested.resolver_match = match
    response = match.func(nested, *match.args, **match.kwargs)
    if hasattr(response, "render"):
        response.render()
    notices = [{"level": message.level, "text": str(message)} for message in messages.get_messages(nested)]
    return response, notices


def target(spec, parameters, lock=False):
    if not spec.entity:
        return None
    queryset = get_model(spec.entity).objects
    if lock:
        queryset = queryset.select_for_update()
    return queryset.get(pk=parameters[spec.key])


def fingerprint(instance):
    if instance is None:
        return ""
    from django.db.models.fields.files import FieldFile
    from django.db.models.fields.files import FieldFile
    data = {field.attname: getattr(instance, field.attname) for field in instance._meta.concrete_fields}
    data = {key: value.name if isinstance(value, FieldFile) else value for key, value in data.items()}
    data = {key: value.name if isinstance(value, FieldFile) else value for key, value in data.items()}
    return hashlib.sha256(json.dumps(data, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()


def describe(request, name, parameters):
    spec, path = validate(name, parameters)
    instance = target(spec, parameters)
    fields = {}
    # Explicit POST-only actions have no read page of their own.
    if spec.fields or name in {"mark_notification_as_read", "portal:organization_player_remove", "prospects:prospect_delete", "prospects:prospect_convert", "performance:youtube_upload_retry", "performance:dailymotion_upload_request", "retry_automation_progress"}:
        for field in spec.fields:
            choices = []
            if instance is not None:
                try:
                    choices = list(instance._meta.get_field(field).flatchoices)
                except Exception:
                    pass
            if field == "action" and name in {"portal:account_toggle", "performance:subscription_toggle"}:
                choices = [["activate", "Activer"], ["deactivate", "Désactiver"]]
            if field == "decision":
                choices = [["reject", "Refuser"], ["link", "Associer à un joueur existant"], ["create", "Créer le joueur"]]
            if field == "job_type":
                from sportsbase_data.models import SportsBaseSyncJob
                choices = list(SportsBaseSyncJob.JobType.choices)
            fields[field] = {"label": field, "type": "text", "value": "", "required": field not in {"player_id", "staff_response", "job_type"}, "choices": choices}
    else:
        form_path = reverse(spec.form_route, kwargs=parameters) if spec.form_route else path
        response, _ = dispatch(request, form_path)
        if response.status_code != 200:
            raise ValueError("Le formulaire de cette action n’est pas disponible pour ce compte.")
        soup = BeautifulSoup(response.content, "html.parser")
        forms = [form for form in soup.find_all("form") if str(form.get("method", "get")).lower() == "post" and urlparse(urljoin(form_path, form.get("action") or form_path)).path == path]
        if not forms:
            raise ValueError("Le formulaire du site n’a pas été trouvé pour cette action.")
        for control in forms[0].select("input[name], select[name], textarea[name], button[name]"):
            key = control["name"]
            if key == "csrfmiddlewaretoken" or control.has_attr("disabled"):
                continue
            kind = control.get("type", "text")
            if kind in {"submit", "button", "reset", "file"}:
                continue
            value = control.get("value", "")
            choices = []
            if control.name == "select":
                kind = "select"
                options = control.find_all("option")
                choices = [[option.get("value", option.get_text()), option.get_text(" ", strip=True)] for option in options]
                selected = [option.get("value", option.get_text()) for option in options if option.has_attr("selected")]
                if not selected and options and not control.has_attr("multiple"):
                    selected = [options[0].get("value", options[0].get_text())]
                value = selected if control.has_attr("multiple") else (selected[0] if selected else "")
            elif control.name == "textarea":
                value = control.get_text()
                kind = "textarea"
            elif kind == "checkbox":
                value = control.has_attr("checked")
            elif kind == "radio" and not control.has_attr("checked"):
                continue
            label = soup.find("label", attrs={"for": control.get("id", "")})
            fields[key] = {"label": label.get_text(" ", strip=True) if label else key, "type": kind, "value": "" if SECRET.search(key) else value, "required": control.has_attr("required"), "choices": choices, "requiresUserInput": bool(SECRET.search(key))}
    snapshot = {"target": fingerprint(instance), "values": {key: value["value"] for key, value in fields.items() if not value.get("requiresUserInput")}}
    baseline = hashlib.sha256(json.dumps(snapshot, sort_keys=True, cls=DjangoJSONEncoder).encode()).hexdigest()
    return {"action": name, "label": spec.label, "parameters": parameters, "fields": fields, "effects": spec.effects, "baseline": baseline, "sourcePath": path}


def prepare(request, name, parameters, changes):
    descriptor = describe(request, name, parameters)
    if not isinstance(changes, dict) or not changes or set(changes) - descriptor["fields"].keys():
        # A toggle/delete/retry can legitimately have no fields.
        if not (changes == {} and descriptor["fields"] == {}):
            raise ValueError("Les champs de l’action sont invalides.")
    values = {key: item["value"] for key, item in descriptor["fields"].items() if not item.get("requiresUserInput")}
    preview = []
    for key, value in changes.items():
        field = descriptor["fields"][key]
        if field.get("requiresUserInput") or isinstance(value, dict) or (isinstance(value, str) and len(value) > 10_000):
            raise ValueError("Ce champ doit être renseigné directement par l’utilisateur, ou sa valeur est invalide.")
        if field["choices"]:
            allowed = {str(choice[0]) for choice in field["choices"]}
            if any(str(item) not in allowed for item in (value if isinstance(value, list) else [value])):
                raise ValueError(f"Valeur non disponible pour {field['label']}.")
        if field["type"] == "checkbox" and type(value) is not bool:
            raise ValueError("Une case à cocher attend un booléen.")
        values[key] = value
        preview.append({"field": key, "label": field["label"], "before": field["value"], "after": value})
    plan = AgentAction.objects.create(owner=request.user, action=name, parameters=parameters, values=values, baseline=descriptor["baseline"], expires_at=timezone.now() + timedelta(minutes=15))
    secure_fields = [{"field": key, "label": value["label"], "required": value["required"]} for key, value in descriptor["fields"].items() if value.get("requiresUserInput")]
    return {"planId": str(plan.pk), "label": descriptor["label"], "changes": preview, "effects": descriptor["effects"], "secureFields": secure_fields, "expiresAt": plan.expires_at.isoformat(), "status": "requires_confirmation", "sourcePath": descriptor["sourcePath"]}


def confirm(request, plan_id, secure_inputs=None, cancel=False):
    with transaction.atomic():
        plan = AgentAction.objects.select_for_update().get(pk=plan_id, owner=request.user)
        if plan.status in {"success", "failed", "cancelled"}:
            return plan.result
        if plan.status != "prepared":
            raise ValueError("Cette action a déjà été lancée. Vérifiez son résultat avant toute nouvelle demande.")
        if cancel:
            plan.status = "cancelled"
            plan.result = {"status": "cancelled", "message": "Action annulée, aucune modification effectuée.", "planId": str(plan.pk)}
            plan.save(update_fields=["status", "result"])
            return plan.result
        if plan.expires_at <= timezone.now():
            raise ValueError("Cette proposition a expiré. Demandez une nouvelle préparation.")
        # Validate secure inputs before consuming the proposal; they are never stored.
        descriptor = describe(request, plan.action, plan.parameters)
        allowed = {key for key, value in descriptor["fields"].items() if value.get("requiresUserInput")}
        secure_inputs = secure_inputs or {}
        if not isinstance(secure_inputs, dict) or set(secure_inputs) - allowed:
            raise ValueError("Champs confidentiels invalides.")
        for key in allowed:
            if descriptor["fields"][key]["required"] and not secure_inputs.get(key):
                raise ValueError("Complétez les champs confidentiels demandés.")
        plan.status = "running"
        plan.save(update_fields=["status"])
    try:
        with transaction.atomic():
            spec, path = validate(plan.action, plan.parameters)
            instance = target(spec, plan.parameters, lock=True)
            if describe(request, plan.action, plan.parameters)["baseline"] != plan.baseline:
                raise ValueError("Les données ont changé depuis la proposition. Demandez une nouvelle préparation.")
            response, notices = dispatch(request, path, "POST", {**plan.values, **secure_inputs})
            errors = [notice["text"] for notice in notices if notice["level"] >= messages.ERROR]
            if response.get("Content-Type", "").startswith("application/json"):
                returned = json.loads(response.content)
                if returned.get("success") is False or returned.get("error"):
                    raise ValueError("Le site a refusé cette action.")
            soup = BeautifulSoup(response.content, "html.parser") if not getattr(response, "streaming", False) else None
            if soup:
                errors.extend(node.get_text(" ", strip=True) for node in soup.select(".invalid-feedback, .errorlist"))
            if response.status_code >= 400 or errors or (response.status_code == 200 and soup and soup.select("form[method=post]") and not any(notice["level"] == messages.SUCCESS for notice in notices)):
                raise ValueError("Le site a refusé cette action : " + (" ; ".join(errors)[:1500] or "vérifiez les champs et les droits."))
            if response.status_code not in {200, 201, 204, 302, 303}:
                raise ValueError("Le résultat de cette action n’est pas confirmé par le site.")
            if response.status_code in {302, 303} and not any(notice["level"] == messages.SUCCESS for notice in notices):
                raise ValueError("Le site n’a pas confirmé la modification. Consultez le formulaire et les droits du compte.")
            result = {"status": "success", "message": f"{spec.label} : action acceptée par MS Football.", "planId": str(plan.pk), "sourcePath": path}
        plan.status = "success"
        plan.result = result
    except Exception as error:
        plan.status = "failed"
        plan.result = {"status": "failed", "message": str(error)[:1800] if isinstance(error, ValueError) else "Le site n’a pas pu terminer cette action. Consultez son état avant de la relancer.", "planId": str(plan.pk)}
    plan.completed_at = timezone.now()
    plan.save(update_fields=["status", "result", "completed_at"])
    return plan.result
