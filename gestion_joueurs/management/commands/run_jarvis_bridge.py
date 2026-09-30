from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.core.management.base import BaseCommand, CommandError

from gestion_joueurs.jarvis_bridge import BridgeError, execute_tool, list_capabilities


MAX_REQUEST_BYTES = 1_000_000


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "MSFootballJarvisBridge/1.0"

    def _json_response(self, status: int, payload) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = getattr(self.server, "bridge_token", "")
        supplied = self.headers.get("Authorization", "")
        if not supplied.startswith("Bearer "):
            return False
        token = supplied[len("Bearer "):].strip()
        return bool(expected) and hmac.compare_digest(token, expected)

    def do_GET(self) -> None:
        if self.path == "/health":
            if not self._authorized():
                self._json_response(401, {"ok": False, "error": "unauthorized"})
                return
            self._json_response(
                200,
                {
                    "ok": True,
                    "service": "ms_football_jarvis_bridge",
                    "capabilities": list_capabilities(),
                },
            )
            return

        self._json_response(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/tool":
            self._json_response(404, {"ok": False, "error": "not_found"})
            return

        if not self._authorized():
            self._json_response(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0

        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json_response(
                400,
                {"ok": False, "error": "invalid_request_size"},
            )
            return

        try:
            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_response(400, {"ok": False, "error": "invalid_json"})
            return

        if not isinstance(payload, dict):
            self._json_response(
                400,
                {"ok": False, "error": "body_must_be_object"},
            )
            return

        tool = str(payload.get("tool") or "").strip()
        arguments = payload.get("arguments") or {}
        if not isinstance(arguments, dict):
            self._json_response(
                400,
                {"ok": False, "error": "arguments_must_be_object"},
            )
            return

        try:
            result = execute_tool(tool, arguments)
        except BridgeError as exc:
            self._json_response(
                400,
                {"ok": False, "error": str(exc)},
            )
            return
        except Exception as exc:
            self._json_response(
                500,
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                },
            )
            return

        self._json_response(
            200,
            {
                "ok": True,
                "tool": tool,
                "result": result,
            },
        )

    def log_message(self, format, *args) -> None:
        # Keep console output useful without echoing Authorization headers or
        # request bodies that may contain private customer/player information.
        print(
            f"[JARVIS_BRIDGE] {self.address_string()} "
            f"{format % args}"
        )


class Command(BaseCommand):
    help = (
        "Run a local authenticated bridge that lets Jarvis inspect/query "
        "MS Football through generic Django tools."
    )

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument(
            "--allow-remote",
            action="store_true",
            help="Allow binding outside loopback. Use only behind a trusted tunnel.",
        )

    def handle(self, *args, **options):
        token = (
            os.getenv("JARVIS_MS_FOOTBALL_BRIDGE_TOKEN")
            or ""
        ).strip()
        if len(token) < 24:
            raise CommandError(
                "JARVIS_MS_FOOTBALL_BRIDGE_TOKEN must be configured "
                "with at least 24 characters."
            )

        host = str(options["host"]).strip()
        port = int(options["port"])
        allow_remote = bool(options["allow_remote"])

        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        if host not in loopback_hosts and not allow_remote:
            raise CommandError(
                "Remote binding is disabled by default. "
                "Use --allow-remote only behind a trusted private tunnel."
            )

        server = ThreadingHTTPServer(
            (host, port),
            BridgeRequestHandler,
        )
        server.bridge_token = token

        self.stdout.write(
            self.style.SUCCESS(
                f"MS Football Jarvis bridge listening on http://{host}:{port}"
            )
        )
        self.stdout.write(
            "Tools: list_capabilities, describe_schema, query_records, "
            "run_readonly_sql, search_code, list_routes, resolve_route, "
            "prepare_mutation, commit_mutation"
        )
        self.stdout.write(
            "No public URL is exposed by default; keep this process local."
        )

        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            self.stdout.write("Stopping Jarvis bridge...")
        finally:
            server.server_close()
