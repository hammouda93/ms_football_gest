from __future__ import annotations

import datetime as dt
import json
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlparse
from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.urls import URLPattern, URLResolver, get_resolver


SENSITIVE_NAMES = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "session_data",
    "private_key",
    "access_token",
    "refresh_token",
}

BLOCKED_SQL_TERMS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "copy",
    "call",
    "execute",
    "merge",
    "replace",
    "vacuum",
    "analyze",
    "refresh",
    "lock",
}

BLOCKED_SQL_SOURCES = {
    "auth_user",
    "django_session",
    "django_migrations",
}

SENSITIVE_CODE_LINE_RE = re.compile(
    r"(?i)\b("
    r"secret_key|telegram_bot_token|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|password|private[_-]?key|authorization"
    r")\b\s*[:=]"
)


CODE_EXTENSIONS = {
    ".py",
    ".html",
    ".js",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
}

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "media",
    "staticfiles",
    ".cache",
}

_PENDING_CHANGES: dict[str, dict[str, Any]] = {}
CHANGE_TTL_SECONDS = 600


class BridgeError(ValueError):
    pass


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "pk"):
        return {
            "pk": _json_value(value.pk),
            "label": str(value),
        }
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def _project_root() -> Path:
    return Path(settings.BASE_DIR).resolve()


def _is_project_app(model) -> bool:
    try:
        app_path = Path(model._meta.app_config.path).resolve()
        app_path.relative_to(_project_root())
        return True
    except Exception:
        return False


def _project_models() -> list[Any]:
    return [
        model
        for model in apps.get_models()
        if _is_project_app(model)
    ]


def _model_key(model) -> str:
    return f"{model._meta.app_label}.{model.__name__}"


def _resolve_model(name: str):
    target = (name or "").strip().lower()
    if not target:
        raise BridgeError("model is required")

    matches = []
    for model in _project_models():
        keys = {
            model.__name__.lower(),
            model._meta.model_name.lower(),
            _model_key(model).lower(),
            f"{model._meta.app_label}.{model._meta.model_name}".lower(),
            model._meta.db_table.lower(),
        }
        if target in keys:
            matches.append(model)

    if not matches:
        raise BridgeError(f"Unknown project model: {name}")
    if len(matches) > 1:
        raise BridgeError(
            "Ambiguous model. Use app_label.ModelName: "
            + ", ".join(_model_key(model) for model in matches[:8])
        )
    return matches[0]


def _is_sensitive_name(name: str) -> bool:
    normalized = (name or "").strip().lower()
    return any(
        token == normalized
        or normalized.endswith("_" + token)
        or token in normalized.split("__")
        for token in SENSITIVE_NAMES
    )


def _field_map(model) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for field in model._meta.get_fields():
        if getattr(field, "auto_created", False) and not getattr(
            field,
            "concrete",
            False,
        ):
            continue
        mapping[field.name] = field
        attname = getattr(field, "attname", None)
        if attname:
            mapping[attname] = field
    return mapping


def _validate_field_path(model, path: str) -> None:
    if not path:
        raise BridgeError("Empty field path")
    segments = path.split("__")
    current = model

    lookup_suffixes = {
        "exact",
        "iexact",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "in",
        "gt",
        "gte",
        "lt",
        "lte",
        "range",
        "isnull",
        "date",
        "year",
        "month",
        "day",
    }

    for index, segment in enumerate(segments):
        if _is_sensitive_name(segment):
            raise BridgeError(f"Sensitive field is not exposed: {segment}")

        mapping = _field_map(current)
        field = mapping.get(segment)
        if field is None:
            if index == len(segments) - 1 and segment in lookup_suffixes:
                return
            raise BridgeError(
                f"Unknown field path {path!r} on {_model_key(current)}"
            )

        related_model = getattr(field, "related_model", None)
        if index < len(segments) - 1:
            next_segment = segments[index + 1]
            if next_segment in lookup_suffixes:
                if index + 1 != len(segments) - 1:
                    raise BridgeError(f"Invalid lookup path: {path}")
                return
            if related_model is None:
                raise BridgeError(
                    f"Field {segment} is not a relation in path {path}"
                )
            current = related_model


def _default_fields(model) -> list[str]:
    fields = []
    for field in model._meta.concrete_fields:
        name = getattr(field, "attname", field.name)
        if _is_sensitive_name(name):
            continue
        fields.append(name)
    return fields[:30]


def list_capabilities() -> dict[str, Any]:
    models = _project_models()
    apps_map: dict[str, list[str]] = {}
    for model in models:
        apps_map.setdefault(model._meta.app_label, []).append(model.__name__)

    return {
        "project": "ms_football_gest",
        "mode": "local_django_bridge",
        "read_tools": [
            "list_capabilities",
            "describe_schema",
            "query_records",
            "run_readonly_sql",
            "search_code",
            "list_routes",
        ],
        "write_tools": [
            "prepare_mutation",
            "commit_mutation",
        ],
        "write_policy": (
            "prepare_mutation never changes data. commit_mutation must only be "
            "called after explicit user approval in Jarvis."
        ),
        "apps": {
            app_label: sorted(names)
            for app_label, names in sorted(apps_map.items())
        },
    }


def describe_schema(
    search: str = "",
    limit_models: int = 80,
) -> dict[str, Any]:
    needle = (search or "").strip().lower()
    output = []

    for model in _project_models():
        model_name = _model_key(model)
        fields = []
        haystack = [model_name.lower(), model._meta.db_table.lower()]

        for field in model._meta.get_fields():
            name = getattr(field, "name", "")
            if not name or _is_sensitive_name(name):
                continue
            related_model = getattr(field, "related_model", None)
            item = {
                "name": name,
                "type": field.__class__.__name__,
                "null": bool(getattr(field, "null", False)),
                "primary_key": bool(getattr(field, "primary_key", False)),
            }
            attname = getattr(field, "attname", None)
            if attname and attname != name:
                item["attname"] = attname
            if related_model is not None:
                item["related_model"] = (
                    f"{related_model._meta.app_label}."
                    f"{related_model.__name__}"
                )
            choices = getattr(field, "choices", None)
            if choices:
                item["choices"] = [
                    [_json_value(value), str(label)]
                    for value, label in list(choices)[:30]
                ]
            fields.append(item)
            haystack.append(name.lower())

        if needle and not any(needle in value for value in haystack):
            continue

        output.append(
            {
                "model": model_name,
                "table": model._meta.db_table,
                "verbose_name": str(model._meta.verbose_name),
                "fields": fields,
            }
        )
        if len(output) >= max(1, min(int(limit_models), 120)):
            break

    return {
        "models": output,
        "count": len(output),
    }


def query_records(
    model: str,
    filters: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    order_by: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    model_cls = _resolve_model(model)
    filters = dict(filters or {})

    for key in filters:
        _validate_field_path(model_cls, str(key))

    selected_fields = list(fields or _default_fields(model_cls))
    if not selected_fields:
        raise BridgeError("At least one field is required")
    for field_name in selected_fields:
        _validate_field_path(model_cls, str(field_name))

    ordering = list(order_by or [])
    for item in ordering:
        field_name = str(item).lstrip("-")
        _validate_field_path(model_cls, field_name)

    safe_limit = max(1, min(int(limit), 200))

    queryset = model_cls.objects.filter(**filters)
    total = queryset.count()
    if ordering:
        queryset = queryset.order_by(*ordering)

    rows = list(
        queryset.values(*selected_fields)[:safe_limit]
    )
    return {
        "model": _model_key(model_cls),
        "filters": _json_value(filters),
        "fields": selected_fields,
        "total_matching": total,
        "returned": len(rows),
        "rows": _json_value(rows),
    }


def _validate_readonly_sql(sql: str) -> str:
    statement_text = (sql or "").strip()
    if not statement_text:
        raise BridgeError("SQL is empty")

    statements = [
        statement
        for statement in sqlparse.parse(statement_text)
        if str(statement).strip()
    ]
    if len(statements) != 1:
        raise BridgeError("Only one SQL statement is allowed")

    statement = statements[0]
    statement_type = statement.get_type().upper()
    lower = statement_text.lower()

    if statement_type != "SELECT" and not lower.startswith("with "):
        raise BridgeError("Only SELECT/CTE queries are allowed")

    if ";" in statement_text.rstrip(";"):
        raise BridgeError("Multiple SQL statements are not allowed")

    padded = " " + re.sub(r"\s+", " ", lower) + " "
    for term in BLOCKED_SQL_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", padded):
            raise BridgeError(f"SQL keyword is not allowed: {term}")

    for source in BLOCKED_SQL_SOURCES:
        if source in lower:
            raise BridgeError(f"Sensitive table is not exposed: {source}")

    for sensitive in SENSITIVE_NAMES:
        if re.search(rf"\b{re.escape(sensitive)}\b", lower):
            raise BridgeError(
                f"Sensitive field/token is not exposed: {sensitive}"
            )

    return statement_text.rstrip(";")


def run_readonly_sql(
    sql: str,
    params: list[Any] | None = None,
    max_rows: int = 100,
) -> dict[str, Any]:
    statement = _validate_readonly_sql(sql)
    parameters = list(params or [])
    row_limit = max(1, min(int(max_rows), 300))

    with transaction.atomic():
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = 5000")
            cursor.execute(statement, parameters)
            columns = [
                item[0]
                for item in (cursor.description or [])
            ]
            raw_rows = cursor.fetchmany(row_limit + 1)

    truncated = len(raw_rows) > row_limit
    raw_rows = raw_rows[:row_limit]
    rows = [
        {
            columns[index]: _json_value(value)
            for index, value in enumerate(row)
        }
        for row in raw_rows
    ]

    return {
        "columns": columns,
        "returned": len(rows),
        "truncated": truncated,
        "rows": rows,
    }


def search_code(
    query: str,
    max_results: int = 20,
) -> dict[str, Any]:
    needle = (query or "").strip()
    if len(needle) < 2:
        raise BridgeError("Code search query is too short")

    root = _project_root()
    lowered = needle.lower()
    matches = []
    max_items = max(1, min(int(max_results), 50))

    for path in root.rglob("*"):
        if len(matches) >= max_items:
            break
        if not path.is_file() or path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue

        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.name.lower().startswith(".env"):
            continue
        if any(
            token in path.name.lower()
            for token in ("secret", "credential", "private_key")
        ):
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue

        hit_lines = [
            index
            for index, line in enumerate(lines)
            if lowered in line.lower()
        ]
        for index in hit_lines[:3]:
            start = max(0, index - 2)
            end = min(len(lines), index + 3)
            rendered = []
            for line_no in range(start, end):
                line = lines[line_no][:240]
                if SENSITIVE_CODE_LINE_RE.search(line):
                    line = "[REDACTED SENSITIVE CONFIGURATION]"
                rendered.append(f"{line_no + 1}: {line}")
            snippet = "\n".join(rendered)
            matches.append(
                {
                    "path": str(relative).replace("\\", "/"),
                    "line": index + 1,
                    "snippet": snippet,
                }
            )
            if len(matches) >= max_items:
                break

    return {
        "query": needle,
        "results": matches,
        "count": len(matches),
    }


def _walk_urlpatterns(
    patterns,
    prefix: str = "",
    output: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    output = output if output is not None else []
    for pattern in patterns:
        current = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            _walk_urlpatterns(pattern.url_patterns, current, output)
            continue
        if not isinstance(pattern, URLPattern):
            continue

        callback = getattr(pattern, "callback", None)
        view_name = ""
        if callback is not None:
            view_name = (
                getattr(callback, "__module__", "")
                + "."
                + getattr(callback, "__name__", callback.__class__.__name__)
            ).strip(".")

        output.append(
            {
                "pattern": current,
                "name": pattern.name,
                "view": view_name,
            }
        )
    return output


def list_routes(
    search: str = "",
    limit: int = 120,
) -> dict[str, Any]:
    needle = (search or "").strip().lower()
    routes = _walk_urlpatterns(get_resolver().url_patterns)
    result = []

    for route in routes:
        text = " ".join(
            str(route.get(key) or "")
            for key in ("pattern", "name", "view")
        ).lower()
        if needle and needle not in text:
            continue
        result.append(route)
        if len(result) >= max(1, min(int(limit), 250)):
            break

    return {
        "routes": result,
        "count": len(result),
    }


def _validate_mutation_values(model_cls, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise BridgeError("values must be a non-empty object")

    mapping = _field_map(model_cls)
    clean: dict[str, Any] = {}
    for name, value in values.items():
        field_name = str(name)
        if _is_sensitive_name(field_name):
            raise BridgeError(f"Sensitive field cannot be changed: {field_name}")
        field = mapping.get(field_name)
        if field is None:
            raise BridgeError(f"Unknown writable field: {field_name}")
        if getattr(field, "primary_key", False):
            raise BridgeError("Primary keys cannot be changed")
        if getattr(field, "auto_created", False):
            raise BridgeError(f"Auto-created field cannot be changed: {field_name}")
        clean[field_name] = value
    return clean


def _cleanup_pending_changes() -> None:
    cutoff = time.time() - CHANGE_TTL_SECONDS
    stale = [
        change_id
        for change_id, item in _PENDING_CHANGES.items()
        if float(item.get("created_at", 0)) < cutoff
    ]
    for change_id in stale:
        _PENDING_CHANGES.pop(change_id, None)


def prepare_mutation(
    model: str,
    operation: str,
    filters: dict[str, Any] | None = None,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _cleanup_pending_changes()

    model_cls = _resolve_model(model)
    op = (operation or "").strip().lower()
    if op not in {"create", "update", "delete"}:
        raise BridgeError("operation must be create, update or delete")

    clean_filters = dict(filters or {})
    for key in clean_filters:
        _validate_field_path(model_cls, str(key))

    clean_values = {}
    if op in {"create", "update"}:
        clean_values = _validate_mutation_values(
            model_cls,
            dict(values or {}),
        )

    preview: dict[str, Any]
    if op == "create":
        preview = {
            "operation": "create",
            "model": _model_key(model_cls),
            "values": _json_value(clean_values),
        }
    else:
        queryset = model_cls.objects.filter(**clean_filters)
        count = queryset.count()
        if count == 0:
            raise BridgeError("No records match this mutation")
        if count > 50:
            raise BridgeError(
                "Mutation affects more than 50 records; narrow the filters first"
            )
        sample = [
            {
                "pk": _json_value(obj.pk),
                "label": str(obj)[:240],
            }
            for obj in queryset[:20]
        ]
        preview = {
            "operation": op,
            "model": _model_key(model_cls),
            "filters": _json_value(clean_filters),
            "values": _json_value(clean_values),
            "count": count,
            "sample": sample,
        }

    change_id = uuid.uuid4().hex
    _PENDING_CHANGES[change_id] = {
        "created_at": time.time(),
        "model": _model_key(model_cls),
        "operation": op,
        "filters": clean_filters,
        "values": clean_values,
    }

    return {
        "change_id": change_id,
        "expires_in_seconds": CHANGE_TTL_SECONDS,
        "requires_user_approval": True,
        "preview": preview,
    }


def commit_mutation(change_id: str) -> dict[str, Any]:
    _cleanup_pending_changes()
    key = (change_id or "").strip()
    item = _PENDING_CHANGES.pop(key, None)
    if item is None:
        raise BridgeError(
            "Unknown or expired change_id. Prepare the mutation again."
        )

    model_cls = _resolve_model(item["model"])
    operation = item["operation"]
    filters = item["filters"]
    values = item["values"]

    with transaction.atomic():
        if operation == "create":
            obj = model_cls(**values)
            obj.full_clean()
            obj.save()
            return {
                "operation": operation,
                "model": _model_key(model_cls),
                "affected": 1,
                "created_pk": _json_value(obj.pk),
                "label": str(obj)[:240],
            }

        queryset = model_cls.objects.select_for_update().filter(**filters)
        objects = list(queryset[:51])
        if not objects:
            raise BridgeError("Records changed since preview; nothing matches now")
        if len(objects) > 50:
            raise BridgeError("Mutation grew beyond 50 records; aborting")

        if operation == "update":
            for obj in objects:
                for name, value in values.items():
                    setattr(obj, name, value)
                obj.full_clean()
                obj.save()
            return {
                "operation": operation,
                "model": _model_key(model_cls),
                "affected": len(objects),
                "pks": [_json_value(obj.pk) for obj in objects],
            }

        if operation == "delete":
            pks = [_json_value(obj.pk) for obj in objects]
            for obj in objects:
                obj.delete()
            return {
                "operation": operation,
                "model": _model_key(model_cls),
                "affected": len(objects),
                "pks": pks,
            }

    raise BridgeError("Unsupported mutation operation")


TOOL_HANDLERS = {
    "list_capabilities": list_capabilities,
    "describe_schema": describe_schema,
    "query_records": query_records,
    "run_readonly_sql": run_readonly_sql,
    "search_code": search_code,
    "list_routes": list_routes,
    "prepare_mutation": prepare_mutation,
    "commit_mutation": commit_mutation,
}


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get((name or "").strip())
    if handler is None:
        raise BridgeError(f"Unknown bridge tool: {name}")
    return _json_value(handler(**dict(arguments or {})))
