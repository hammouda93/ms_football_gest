"""Technical internal-read credentials, sanitized audit and shared quota.

No business model imports, request bodies or credential values enter logs.
"""
import hashlib
import hmac
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.db import DatabaseError, connections
from django.utils.connection import ConnectionDoesNotExist


READ_SCOPE = "business:read:all"


class AccessDenied(Exception):
    """Public, fixed-text error safe for HTTP translation."""

    _ERRORS = {
        "disabled": (404, "Data access is disabled."),
        "unauthorized": (401, "Valid service credentials required."),
        "forbidden": (403, "Internal global read scope required."),
        "access_unavailable": (503, "Technical access is unavailable."),
        "quota_exceeded": (429, "Technical read budget exhausted."),
    }

    def __init__(self, code):
        self.status, self.message = self._ERRORS[code]
        self.code = code
        super().__init__(self.message)


def authenticate_request(request):
    """Authenticate a bearer token without accepting a Django session identity."""
    if getattr(settings, "DATA_ACCESS_ENABLED", False) is not True:
        raise AccessDenied("disabled")
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if (not isinstance(header, str) or len(header) > 512
            or not re.fullmatch(r"(?i:Bearer) [A-Za-z0-9._~+/-]+=*", header)):
        raise AccessDenied("unauthorized")
    digest = hashlib.sha256(header[7:].encode("ascii")).hexdigest()
    configured = getattr(settings, "DATA_ACCESS_CREDENTIALS", [])
    if not isinstance(configured, list) or len(configured) > 256:
        raise AccessDenied("unauthorized")
    matches = []
    now = datetime.now(timezone.utc)
    for entry in configured:
        if not isinstance(entry, dict):
            continue
        expected = entry.get("token_hash")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            continue
        # Compare all well-formed hashes, not just the first match.
        if hmac.compare_digest(digest, expected):
            matches.append(entry)
    if len(matches) != 1:
        raise AccessDenied("unauthorized")
    entry = matches[0]
    identity = entry.get("id")
    expiry = entry.get("expires_at")
    if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity)
            or entry.get("revoked", False) is not False or not isinstance(expiry, str)):
        raise AccessDenied("unauthorized")
    try:
        expires_at = datetime.fromisoformat(expiry)
        if expires_at.tzinfo is None or expires_at.utcoffset() is None or expires_at <= now:
            raise ValueError("expired or naive")
    except (ValueError, TypeError, OverflowError):
        raise AccessDenied("unauthorized") from None
    if entry.get("scope") != READ_SCOPE:
        raise AccessDenied("forbidden")
    return {"id": identity, "scope": READ_SCOPE}


def fingerprint(query):
    """Canonical JSON SHA-256; callers log only the digest, never the input."""
    encoded = json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


_AUDIT_CODES = frozenset({
    "ok", "disabled", "unauthorized", "forbidden", "access_unavailable", "quota_exceeded",
    "method_not_allowed", "invalid_body", "invalid_query", "response_too_large", "busy",
    "database_read_failed", "internal_error",
})


def emit_audit(event=None, **fields):
    """Emit a bounded JSON allowlist record, not arbitrary request/log context.

    Identifier slots must come from trusted principal/catalog metadata, never
    user query values. Lexical validation is not a business-data classifier.
    """
    source = dict(event) if isinstance(event, dict) else {}
    source.update(fields)
    clean = {}
    patterns = {
        "principalId": r"[A-Za-z0-9_-]{1,64}",
        "requestId": r"[0-9a-f]{32}",
        "queryHash": r"[0-9a-f]{64}",
        "schemaFingerprint": r"[0-9a-f]{64}",
        "entity": r"[A-Za-z_][A-Za-z0-9_.]{0,127}",
    }
    for key, pattern in patterns.items():
        value = source.get(key)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            clean[key] = value
    value = source.get("fields")
    if (isinstance(value, (list, tuple)) and len(value) <= 200
            and all(isinstance(item, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,127}", item) for item in value)):
        clean["fields"] = list(value)
    rows = source.get("rowCount")
    if type(rows) is int and 0 <= rows <= 2**63 - 1:
        clean["rowCount"] = rows
    duration = source.get("durationMs")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 <= duration <= 86_400_000 and math.isfinite(duration):
        clean["durationMs"] = duration
    code = source.get("code")
    if isinstance(code, str) and code in _AUDIT_CODES:
        clean["code"] = code
    status = source.get("status")
    if type(status) is int and 100 <= status <= 599:
        clean["status"] = status
    logging.getLogger("data_access.audit").info(json.dumps(clean, sort_keys=True, separators=(",", ":"), allow_nan=False))


class QuotaError(AccessDenied):
    """A committed budget has been exhausted; no business read is permitted."""

    def __init__(self, retry_after):
        super().__init__("quota_exceeded")
        self.retry_after = retry_after


def reserve_budget(principal_id):
    """Reserve one shared fixed-minute read; must precede read_transaction."""
    if getattr(settings, "DATA_ACCESS_ENABLED", False) is not True:
        raise AccessDenied("disabled")
    if not isinstance(principal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", principal_id):
        raise AccessDenied("forbidden")
    for name, default in (("DATA_ACCESS_REQUESTS_PER_MINUTE", 50), ("DATA_ACCESS_GLOBAL_REQUESTS_PER_MINUTE", 100)):
        value = getattr(settings, name, default)
        if type(value) is not int or not 1 <= value <= 1_000_000:
            raise AccessDenied("access_unavailable")
    configured = connections.databases.get("data_access", {})
    if (configured.get("ENGINE") != "django.db.backends.postgresql"
            or configured.get("ATOMIC_REQUESTS", False) is not False):
        raise AccessDenied("access_unavailable")
    try:
        connection = connections["data_access"]
        if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
            raise AccessDenied("access_unavailable")
    except (DatabaseError, ConnectionDoesNotExist):
        raise AccessDenied("access_unavailable") from None
    from django.db import transaction

    limits = (
        getattr(settings, "DATA_ACCESS_GLOBAL_REQUESTS_PER_MINUTE", 100),
        getattr(settings, "DATA_ACCESS_REQUESTS_PER_MINUTE", 50),
    )
    keys = (
        hashlib.sha256(b"data_access:global:v1").hexdigest(),
        hashlib.sha256(b"data_access:principal:v1:" + principal_id.encode("ascii")).hexdigest(),
    )
    try:
        # Advisory lock and both counters must share the same committed txn.
        # This deliberately serializes only the short quota write, not reads.
        with transaction.atomic(using="data_access"):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute("SET LOCAL lock_timeout = '2000ms'")
                cursor.execute("SET LOCAL statement_timeout = '3000ms'")
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [5264196713031921])
                cursor.execute("SELECT clock_timestamp()")
                now = cursor.fetchone()[0].astimezone(timezone.utc)
                window = now.replace(second=0, microsecond=0)
                cursor.execute(
                    "SELECT principal_hash, requests FROM public.data_access_read_budget "
                    "WHERE window_start = %s AND principal_hash IN (%s, %s) FOR UPDATE",
                    [window, *keys],
                )
                counts = dict(cursor.fetchall())
                if any(counts.get(key, 0) >= limit for key, limit in zip(keys, limits)):
                    raise QuotaError(max(1, math.ceil((window + timedelta(minutes=1) - now).total_seconds())))
                cursor.execute(
                    "INSERT INTO public.data_access_read_budget (principal_hash, window_start, requests) "
                    "VALUES (%s, %s, 1), (%s, %s, 1) "
                    "ON CONFLICT (principal_hash, window_start) DO UPDATE "
                    "SET requests = public.data_access_read_budget.requests + 1",
                    [keys[0], window, keys[1], window],
                )
                cursor.execute(
                    "DELETE FROM public.data_access_read_budget WHERE id IN "
                    "(SELECT id FROM public.data_access_read_budget WHERE window_start < %s "
                    "ORDER BY window_start, id LIMIT 1000)",
                    [window - timedelta(minutes=2)],
                )
    except DatabaseError:
        raise AccessDenied("access_unavailable") from None
