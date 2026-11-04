import re

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models
from django.db.models import Avg, Count, Max, Min, Sum


BUSINESS_APPS = {"gestion_joueurs", "client_portal", "sportsbase_data", "prospects"}
SECRET = re.compile(r"password|secret|token|api.?key|credential", re.I)
USER_FIELDS = {"id", "username", "first_name", "last_name", "email", "is_active", "is_staff", "is_superuser", "date_joined", "last_login"}
LOOKUPS = {"exact", "iexact", "icontains", "contains", "startswith", "istartswith", "gt", "gte", "lt", "lte", "in", "isnull", "year", "month", "date", "range"}


def scrub(value):
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if not SECRET.search(str(key))}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def permitted_models():
    return [model for model in apps.get_models() if model._meta.app_label in BUSINESS_APPS or model._meta.label_lower == "auth.user"]


def get_model(label):
    if not isinstance(label, str):
        raise ValueError("Une entité doit être indiquée.")
    candidates = {model._meta.label_lower: model for model in permitted_models()}
    if label.lower() not in candidates:
        raise ValueError("Cette entité n’est pas accessible à l’agent.")
    return candidates[label.lower()]


def safe_field(model, name):
    field = model._meta.get_field(name)
    if not field.concrete or field.many_to_many or SECRET.search(field.name):
        raise ValueError("Ce champ n’est pas accessible à l’agent.")
    if model._meta.label_lower == "auth.user" and field.name not in USER_FIELDS:
        raise ValueError("Ce champ du compte n’est pas accessible.")
    return field


def field_path(model, path, filtering=False):
    if not isinstance(path, str) or len(path) > 160:
        raise ValueError("Champ invalide.")
    parts = path.split("__")
    lookup = None
    if filtering and len(parts) > 1 and parts[-1] in LOOKUPS:
        lookup = parts.pop()
    if not parts or len(parts) > 4:
        raise ValueError("Relation trop profonde.")
    current = model
    for index, name in enumerate(parts):
        field = safe_field(current, name)
        if index < len(parts) - 1:
            if not field.is_relation or field.related_model not in permitted_models():
                raise ValueError("Relation non accessible.")
            current = field.related_model
    return field, lookup


def catalog():
    return [{"entity": model._meta.label_lower, "label": str(model._meta.verbose_name_plural), "primaryKey": model._meta.pk.name} for model in permitted_models()]


def describe(label):
    model = get_model(label)
    fields = []
    for field in model._meta.concrete_fields:
        try:
            safe_field(model, field.name)
        except ValueError:
            continue
        fields.append({"name": field.name, "type": field.get_internal_type(), "label": str(field.verbose_name), "nullable": field.null, "choices": list(field.flatchoices) if field.choices else [], "relation": field.related_model._meta.label_lower if field.is_relation else None})
    return {"entity": model._meta.label_lower, "fields": fields, "lookups": sorted(LOOKUPS), "readOnlyDatabase": True}


def query(payload):
    if not isinstance(payload, dict) or set(payload) - {"entity", "fields", "filters", "orderBy", "limit", "offset", "aggregates", "groupBy"}:
        raise ValueError("Demande de consultation invalide.")
    model = get_model(payload.get("entity"))
    filters = payload.get("filters", {})
    if not isinstance(filters, dict) or len(filters) > 12:
        raise ValueError("Filtres invalides.")
    for path, value in filters.items():
        _, lookup = field_path(model, path, filtering=True)
        if lookup in {"in", "range"} and (not isinstance(value, list) or len(value) > 100 or (lookup == "range" and len(value) != 2)):
            raise ValueError("Liste de filtre invalide.")
        if lookup == "isnull" and not isinstance(value, bool):
            raise ValueError("isnull attend un booléen.")
        if isinstance(value, dict) or (isinstance(value, list) and lookup not in {"in", "range"}):
            raise ValueError("Valeur de filtre invalide.")
    limit, offset = payload.get("limit", 25), payload.get("offset", 0)
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Pagination invalide.")
    queryset = model.objects.filter(**filters)
    aggregates = payload.get("aggregates", [])
    groups = payload.get("groupBy", [])
    if not isinstance(aggregates, list) or len(aggregates) > 10 or not isinstance(groups, list) or len(groups) > 3:
        raise ValueError("Agrégations invalides.")
    if groups and not aggregates:
        raise ValueError("Un regroupement doit préciser les agrégations.")
    for group in groups:
        field_path(model, group)
    functions = {"count": Count, "sum": Sum, "avg": Avg, "min": Min, "max": Max}
    annotations = {}
    for item in aggregates:
        if not isinstance(item, dict) or set(item) != {"function", "field", "alias"}:
            raise ValueError("Agrégation invalide.")
        function, path, alias = item["function"], item["field"], item["alias"]
        if function not in functions or not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", alias) or alias in annotations:
            raise ValueError("Nom d’agrégation invalide.")
        field, _ = field_path(model, path)
        if function in {"sum", "avg"} and not isinstance(field, (models.IntegerField, models.DecimalField, models.FloatField)):
            raise ValueError("Une somme ou moyenne exige un champ numérique.")
        annotations[alias] = functions[function](path)
    if annotations:
        if groups:
            result = queryset.order_by().values(*groups).annotate(**annotations).order_by(*groups)
            total = result.count()
            return {"entity": model._meta.label_lower, "total": total, "rows": scrub(list(result[offset:offset + limit])), "limit": limit, "offset": offset, "hasMore": total > offset + limit}
        return {"entity": model._meta.label_lower, "total": queryset.count(), "aggregates": scrub(queryset.aggregate(**annotations))}
    fields = payload.get("fields")
    if fields is None:
        fields = [field["name"] for field in describe(model._meta.label_lower)["fields"]]
    if not isinstance(fields, list) or not 1 <= len(fields) <= 80:
        raise ValueError("Sélection de champs invalide.")
    for path in fields:
        field_path(model, path)
    order = payload.get("orderBy", [model._meta.pk.name])
    if not isinstance(order, list) or len(order) > 4:
        raise ValueError("Tri invalide.")
    for path in order:
        if not isinstance(path, str):
            raise ValueError("Tri invalide.")
        field_path(model, path.lstrip("-"))
    # The PK makes pagination deterministic even when several rows share a sort key.
    if model._meta.pk.name not in [path.lstrip("-") for path in order]:
        order = [*order, model._meta.pk.name]
    total = queryset.count()
    return {"entity": model._meta.label_lower, "total": total, "rows": scrub(list(queryset.order_by(*order).values(*fields)[offset:offset + limit])), "limit": limit, "offset": offset, "hasMore": total > offset + limit}
