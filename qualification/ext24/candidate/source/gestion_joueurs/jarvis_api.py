from __future__ import annotations

import hmac
import json
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .jarvis_bridge import BridgeError, execute_tool, list_capabilities


MAX_REQUEST_BYTES = 1_000_000


def _expected_token() -> str:
    return (os.getenv("JARVIS_MS_FOOTBALL_BRIDGE_TOKEN") or "").strip()


def _authorized(request) -> bool:
    expected = _expected_token()
    header = request.headers.get("Authorization", "")
    if not expected or not header.startswith("Bearer "):
        return False
    supplied = header[len("Bearer "):].strip()
    return hmac.compare_digest(supplied, expected)


def _unauthorized():
    return JsonResponse(
        {"ok": False, "error": "unauthorized"},
        status=401,
    )


@require_GET
def jarvis_agent_health(request):
    if not _authorized(request):
        return _unauthorized()

    return JsonResponse(
        {
            "ok": True,
            "service": "ms_football_jarvis_bridge",
            "mode": "django_https",
            "capabilities": list_capabilities(),
        }
    )


@csrf_exempt
@require_POST
def jarvis_agent_tool(request):
    if not _authorized(request):
        return _unauthorized()

    content_length = request.META.get("CONTENT_LENGTH") or "0"
    try:
        length = int(content_length)
    except (TypeError, ValueError):
        length = 0

    if length <= 0 or length > MAX_REQUEST_BYTES:
        return JsonResponse(
            {"ok": False, "error": "invalid_request_size"},
            status=400,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse(
            {"ok": False, "error": "invalid_json"},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"ok": False, "error": "body_must_be_object"},
            status=400,
        )

    tool = str(payload.get("tool") or "").strip()
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        return JsonResponse(
            {"ok": False, "error": "arguments_must_be_object"},
            status=400,
        )

    # commit_mutation remains a second-step operation. Jarvis only sends this
    # header after the user has explicitly approved the prepared change.
    if tool == "commit_mutation":
        approved = (
            request.headers.get("X-Jarvis-Approved", "")
            .strip()
            .lower()
        )
        if approved != "yes":
            return JsonResponse(
                {
                    "ok": False,
                    "error": "explicit_approval_required",
                },
                status=403,
            )

    try:
        result = execute_tool(tool, arguments)
    except BridgeError as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc)},
            status=400,
        )
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc)[:500],
            },
            status=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "tool": tool,
            "result": result,
        }
    )
