from __future__ import annotations

import base64
import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from mcp_ops_server.config import (
    EffectiveWebGatewayOptions,
    default_web_gateway_options_config_path,
    load_web_gateway_options,
    update_web_gateway_options,
    validate_web_gateway_options_patch,
)
from mcp_ops_server.branding import (
    ADMIN_TOKEN_HEADER,
    LEGACY_ADMIN_TOKEN_HEADER,
    LEGACY_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
)
from mcp_ops_server.config.user_config import UserConfig, get_default_user_config
from mcp_ops_server.tools import register_tools
from mcp_ops_server.web.gateway_settings import build_gateway_settings_bundle
from mcp_ops_server.web.login_console import build_login_console_bundle


GATEWAY_SCHEMA_VERSION = "hosted-bs-gateway-v1"
DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 8765
MAX_REQUEST_BODY_BYTES = 1024 * 1024


@dataclass
class GatewayConfig:
    host: str = DEFAULT_GATEWAY_HOST
    port: int = DEFAULT_GATEWAY_PORT
    admin_token: str | None = None
    options_file: str | None = None
    options: EffectiveWebGatewayOptions = field(default_factory=load_web_gateway_options)
    user_config: UserConfig = field(default_factory=get_default_user_config)
    session_secret: str = field(default_factory=lambda: os.environ.get("TMP_MCP_SESSION_SECRET", "tmp-mcp-default-session-secret"))

    @property
    def mutating_requests_enabled(self) -> bool:
        if not self.options.enable_mutation_apis:
            return False
        if self.options.require_admin_token_for_mutation:
            return bool(self.admin_token)
        return True


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def tool(self):
        def deco(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
            self.tools[fn.__name__] = fn
            return fn

        return deco


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        config: GatewayConfig,
        tools: dict[str, Callable[..., dict[str, Any]]],
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.gateway_config = config
        self.gateway_tools = tools


class GatewayRequestHandler(BaseHTTPRequestHandler):
    server_version = "tmp-mcp-web-gateway/0.1"

    def do_GET(self) -> None:  # noqa: N802
        route, query = _parse_request_target(self.path)
        if route == "/":
            self._send_redirect(_default_page_path(self.server.gateway_config))
            return
        if route == "/login":
            bundle = build_login_console_bundle(page_type="login", include_html=True)
            self._send_html(HTTPStatus.OK, bundle["html"])
            return
        if route == "/register":
            bundle = build_login_console_bundle(page_type="register", include_html=True)
            self._send_html(HTTPStatus.OK, bundle["html"])
            return
        if route == "/healthz":
            self._send_json(HTTPStatus.OK, _health_payload(self.server.gateway_config))
            return
        if route == "/api/routes":
            if not self.server.gateway_config.options.show_api_index:
                self._send_json(HTTPStatus.NOT_FOUND, _error_payload("route index disabled by gateway options", route=route))
                return
            self._send_json(HTTPStatus.OK, _routes_payload(self.server.gateway_config))
            return
        if route == "/api/gateway/options":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "schema_version": GATEWAY_SCHEMA_VERSION,
                    "data": {"options": self.server.gateway_config.options.to_public_dict(include_sources=True)},
                },
            )
            return
        if route == "/api/auth/sessions":
            # Return list of currently logged-in approvers for login status check
            approvers = self._get_active_approvers()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "schema_version": GATEWAY_SCHEMA_VERSION,
                    "data": {"approvers": approvers},
                },
            )
            return
        if route == "/gateway-settings":
            if not self.server.gateway_config.options.show_gateway_settings:
                self._send_json(HTTPStatus.NOT_FOUND, _error_payload("gateway settings page disabled", route=route))
                return
            self._send_gateway_settings_page()
            return
        if route == "/approvals":
            if not self.server.gateway_config.options.enable_approval_console:
                self._send_json(HTTPStatus.NOT_FOUND, _error_payload("approval console disabled by gateway options", route=route))
                return
            session = self._get_session_from_request()
            if not session:
                self._send_redirect("/login")
                return
            self._send_console_page(
                "get_approval_console_bundle_tool",
                "console_bundle",
                _approval_console_kwargs(query, include_html=True),
            )
            return
        if route == "/config-admin":
            if not self.server.gateway_config.options.enable_config_admin_console:
                self._send_json(HTTPStatus.NOT_FOUND, _error_payload("config admin console disabled by gateway options", route=route))
                return
            session = self._get_session_from_request()
            if not session:
                self._send_redirect("/login")
                return
            self._send_console_page(
                "get_config_admin_console_bundle_tool",
                "config_bundle",
                _config_console_kwargs(query, include_html=True),
            )
            return
        if route == "/api/approval-console":
            if not self._read_api_allowed(route, require_page="approvals"):
                return
            self._send_tool_json(
                "get_approval_console_bundle_tool",
                _approval_console_kwargs(query, include_html=_query_bool(query, "include_html", False)),
            )
            return
        if route == "/api/config-admin-console":
            if not self._read_api_allowed(route, require_page="config-admin"):
                return
            self._send_tool_json(
                "get_config_admin_console_bundle_tool",
                _config_console_kwargs(query, include_html=_query_bool(query, "include_html", False)),
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, _error_payload("route not found", route=route))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers("application/json; charset=utf-8")
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Authorization, Content-Type, {ADMIN_TOKEN_HEADER}, {LEGACY_ADMIN_TOKEN_HEADER}")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        route, _query = _parse_request_target(self.path)

        if route == "/api/auth/login":
            body = self._read_json_body()
            if body is None:
                return
            username = body.get("username", "").strip()
            password = body.get("password", "")
            if not username or not password:
                self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("username and password required", route=route))
                return
            ok, result = self.server.gateway_config.user_config.verify_user(username, password)
            if not ok:
                self._send_json(HTTPStatus.UNAUTHORIZED, _error_payload(str(result), route=route))
                return
            user = result
            self.server.gateway_config.user_config.update_last_login(username)
            session = _create_session(username, user, self.server.gateway_config.session_secret)
            self._send_json(HTTPStatus.OK, {
                "ok": True,
                "schema_version": GATEWAY_SCHEMA_VERSION,
                "summary": "Login successful",
                "data": {"session": session},
            }, extra_headers={"Set-Cookie": _create_session_cookie(session)})
            return

        if route == "/api/auth/register":
            ok, reason = self._authorized_for_gateway_admin()
            if not ok:
                self._discard_request_body()
                self._send_json(HTTPStatus.FORBIDDEN, _error_payload(reason, route=route, auth_required=True))
                return
            body = self._read_json_body()
            if body is None:
                return
            username = body.get("username", "").strip()
            password = body.get("password", "")
            if not username or not password:
                self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("username and password required", route=route))
                return
            ok, message = self.server.gateway_config.user_config.create_user(username, password)
            if not ok:
                self._send_json(HTTPStatus.BAD_REQUEST, _error_payload(message, route=route))
                return
            user = self.server.gateway_config.user_config.get_user(username)
            if not user:
                self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("failed to create user", route=route))
                return
            self.server.gateway_config.user_config.update_last_login(username)
            session = _create_session(username, user, self.server.gateway_config.session_secret)
            self._send_json(HTTPStatus.OK, {
                "ok": True,
                "schema_version": GATEWAY_SCHEMA_VERSION,
                "summary": "Registration successful",
                "data": {"session": session},
            }, extra_headers={"Set-Cookie": _create_session_cookie(session)})
            return

        if route in {"/api/gateway/options/validate", "/api/gateway/options/update"}:
            ok, reason = self._authorized_for_gateway_admin()
            if not ok:
                self._discard_request_body()
                self._send_json(HTTPStatus.FORBIDDEN, _error_payload(reason, route=route, auth_required=True))
                return
            body = self._read_json_body()
            if body is None:
                return
            patch = body.get("config_patch")
            if not isinstance(patch, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("config_patch must be a json object", route=route))
                return
            if route.endswith("/validate"):
                validation = validate_web_gateway_options_patch(
                    patch,
                    config_file=self.server.gateway_config.options_file,
                )
                self._send_json(
                    HTTPStatus.OK if validation.ok else HTTPStatus.BAD_REQUEST,
                    {
                        "ok": validation.ok,
                        "schema_version": GATEWAY_SCHEMA_VERSION,
                        "summary": "Gateway options validation passed."
                        if validation.ok
                        else "Gateway options validation failed.",
                        "data": {"validation": validation.to_dict()},
                        "next_actions": [
                            "Submit /api/gateway/options/update with the same patch after validation passes."
                        ],
                    },
                )
                return
            result = update_web_gateway_options(
                patch,
                updated_by=str(body.get("updated_by") or "gateway-admin"),
                change_reason=body.get("change_reason"),
                config_file=self.server.gateway_config.options_file,
            )
            if result.get("ok"):
                self.server.gateway_config.options = load_web_gateway_options(
                    config_file=self.server.gateway_config.options_file
                )
            self._send_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST, result)
            return

        mutation_routes = {
            "/api/approvals/issue-token": ("issue_enterprise_approval_token_tool", _issue_token_kwargs),
            "/api/approvals/decision": ("record_operation_approval_tool", _record_decision_kwargs),
            "/api/config/validate": ("validate_approval_identity_config_tool", _validate_config_kwargs),
            "/api/config/update": ("update_approval_identity_config_tool", _update_config_kwargs),
            "/api/config/rotate-secret": ("rotate_approval_identity_secret_tool", _rotate_secret_kwargs),
        }
        if route not in mutation_routes:
            self._send_json(HTTPStatus.NOT_FOUND, _error_payload("route not found", route=route))
            return

        ok, reason = self._authorized_for_mutation()
        if not ok:
            self._discard_request_body()
            self._send_json(HTTPStatus.FORBIDDEN, _error_payload(reason, route=route, auth_required=True))
            return

        body = self._read_json_body()
        if body is None:
            return

        tool_name, parser = mutation_routes[route]
        try:
            kwargs = parser(body)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, _error_payload(str(exc), route=route))
            return
        self._send_tool_json(tool_name, kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("TMP_MCP_GATEWAY_QUIET") == "true":
            return
        super().log_message(format, *args)

    def _send_console_page(self, tool_name: str, bundle_key: str, kwargs: dict[str, Any]) -> None:
        result = self._call_tool(tool_name, kwargs)
        if not result.get("ok"):
            status = HTTPStatus.NOT_FOUND if "not found" in str(result.get("summary", "")).lower() else HTTPStatus.BAD_GATEWAY
            self._send_json(status, result)
            return
        bundle = result.get("data", {}).get(bundle_key)
        html = bundle.get("html") if isinstance(bundle, dict) else None
        if not isinstance(html, str) or not html.strip():
            self._send_json(HTTPStatus.BAD_GATEWAY, _error_payload("console bundle did not include html", tool=tool_name))
            return
        self._send_html(HTTPStatus.OK, html)

    def _send_tool_json(self, tool_name: str, kwargs: dict[str, Any]) -> None:
        result = self._call_tool(tool_name, kwargs)
        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
        self._send_json(status, result)

    def _send_gateway_settings_page(self) -> None:
        bundle = build_gateway_settings_bundle(
            options_state=self.server.gateway_config.options.to_public_dict(include_sources=True),
            routes_state=_routes_payload(self.server.gateway_config),
            include_html=True,
        )
        html = bundle.get("html")
        if not isinstance(html, str) or not html.strip():
            self._send_json(HTTPStatus.BAD_GATEWAY, _error_payload("gateway settings bundle did not include html"))
            return
        self._send_html(HTTPStatus.OK, html)

    def _read_api_allowed(self, route: str, *, require_page: str) -> bool:
        options = self.server.gateway_config.options
        if not options.enable_read_apis:
            self._send_json(HTTPStatus.FORBIDDEN, _error_payload("read APIs disabled by gateway options", route=route))
            return False
        if require_page == "approvals" and not options.enable_approval_console:
            self._send_json(HTTPStatus.NOT_FOUND, _error_payload("approval console disabled by gateway options", route=route))
            return False
        if require_page == "config-admin" and not options.enable_config_admin_console:
            self._send_json(HTTPStatus.NOT_FOUND, _error_payload("config admin console disabled by gateway options", route=route))
            return False
        return True

    def _call_tool(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        tool = self.server.gateway_tools.get(tool_name)
        if tool is None:
            return _error_payload("tool not registered", tool=tool_name)
        try:
            result = tool(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive gateway boundary
            return _error_payload("tool call failed", tool=tool_name, error=str(exc))
        if isinstance(result, dict):
            return result
        return _error_payload("tool returned non-json result", tool=tool_name, result_type=type(result).__name__)

    def _read_json_body(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("invalid content-length"))
            return None
        if length <= 0:
            return {}
        if length > MAX_REQUEST_BODY_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, _error_payload("request body too large"))
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("request body must be utf-8 json"))
            return None
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, _error_payload("request body must be a json object"))
            return None
        return payload

    def _discard_request_body(self) -> None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            return
        if length > 0:
            self.rfile.read(min(length, MAX_REQUEST_BODY_BYTES))

    def _authorized_for_mutation(self) -> tuple[bool, str]:
        if not self.server.gateway_config.options.enable_mutation_apis:
            return False, "mutation APIs disabled by gateway options"
        return self._authorized_for_gateway_admin()

    def _get_session_from_request(self) -> dict[str, Any] | None:
        """Extract and validate session from request headers or cookies."""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            session_json = auth[7:].strip()
            try:
                session = json.loads(session_json)
                ok, _ = _verify_session(session, self.server.gateway_config.session_secret)
                return session if ok else None
            except (json.JSONDecodeError, ValueError, TypeError):
                return None
        session = _parse_session_cookie(self.headers.get("Cookie"))
        if session:
            ok, _ = _verify_session(session, self.server.gateway_config.session_secret)
            return session if ok else None
        return None

    def _get_active_approvers(self) -> list[str]:
        """Return usernames that have logged in at least once."""
        approvers = []
        try:
            for user_info in self.server.gateway_config.user_config.list_users():
                if not isinstance(user_info, dict):
                    continue
                username = str(user_info.get("username") or "").strip()
                if username and user_info.get("last_login"):
                    approvers.append(username)
        except Exception:
            pass
        return approvers

    def _authorized_for_gateway_admin(self) -> tuple[bool, str]:
        token = self.server.gateway_config.admin_token
        if self.server.gateway_config.options.require_admin_token_for_mutation and not token:
            return False, "TMP_MCP_GATEWAY_ADMIN_TOKEN is not configured"
        if not self.server.gateway_config.options.require_admin_token_for_mutation:
            return True, "authorized"
        supplied = self.headers.get(ADMIN_TOKEN_HEADER) or self.headers.get(LEGACY_ADMIN_TOKEN_HEADER) or ""
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if secrets.compare_digest(supplied, token):
            return True, "authorized"
        return False, "invalid gateway admin token"

    def _send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self._send_common_headers("text/plain; charset=utf-8")
        self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(b"redirecting")

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self._send_common_headers("text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_common_headers("application/json; charset=utf-8")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_common_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")


def create_gateway_server(
    *,
    host: str | None = None,
    port: int | None = None,
    admin_token: str | None = None,
    options_file: str | None = None,
) -> GatewayServer:
    options = load_web_gateway_options(config_file=options_file)
    config = GatewayConfig(
        host=host or os.environ.get("TMP_MCP_GATEWAY_HOST") or DEFAULT_GATEWAY_HOST,
        port=int(port if port is not None else os.environ.get("TMP_MCP_GATEWAY_PORT") or DEFAULT_GATEWAY_PORT),
        admin_token=admin_token if admin_token is not None else os.environ.get("XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN") or os.environ.get("TMP_MCP_GATEWAY_ADMIN_TOKEN") or "qingxuan",
        options_file=options.primary_config_path or str(default_web_gateway_options_config_path()),
        options=options,
    )
    registry = ToolRegistry()
    register_tools(registry)  # type: ignore[arg-type]
    return GatewayServer((config.host, config.port), GatewayRequestHandler, config=config, tools=registry.tools)


def serve_gateway(
    *,
    host: str | None = None,
    port: int | None = None,
    admin_token: str | None = None,
    options_file: str | None = None,
) -> None:
    server = create_gateway_server(host=host, port=port, admin_token=admin_token, options_file=options_file)
    bound_host, bound_port = server.server_address[:2]
    print(f"tmp-MCP B/S gateway listening on http://{bound_host}:{bound_port}/", flush=True)
    print(f"Gateway settings: http://{bound_host}:{bound_port}/gateway-settings", flush=True)
    if not server.gateway_config.mutating_requests_enabled:
        if not server.gateway_config.options.enable_mutation_apis:
            print("Business mutation APIs are disabled by gateway options.", flush=True)
        else:
            print("Business mutation APIs are disabled until TMP_MCP_GATEWAY_ADMIN_TOKEN is configured.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _approval_console_kwargs(query: dict[str, list[str]], *, include_html: bool) -> dict[str, Any]:
    return {
        "approval_id": _query_text(query, "approval_id"),
        "limit": _query_int(query, "limit", 20),
        "status": _query_text(query, "status"),
        "include_audit_events": _query_bool(query, "include_audit_events", True),
        "audit_limit": _query_int(query, "audit_limit", 50),
        "include_html": include_html,
    }


def _config_console_kwargs(query: dict[str, list[str]], *, include_html: bool) -> dict[str, Any]:
    return {
        "include_html": include_html,
        "include_audit_events": _query_bool(query, "include_audit_events", True),
        "audit_limit": _query_int(query, "audit_limit", 50),
    }


def _issue_token_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return _required_kwargs(
        body,
        required=("approval_id", "decision", "approver", "enterprise_assertion"),
        allowed=("approval_id", "decision", "approver", "enterprise_assertion", "expires_in_minutes", "comment"),
    )


def _record_decision_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return _required_kwargs(
        body,
        required=("approval_id", "decision", "approver"),
        allowed=("approval_id", "decision", "approver", "comment", "expires_in_minutes", "approval_token"),
    )


def _validate_config_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return _required_kwargs(
        body,
        required=("config_patch",),
        allowed=("config_patch", "include_sources", "session_id", "trace_id"),
    )


def _update_config_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return _required_kwargs(
        body,
        required=("config_patch", "admin_approver", "admin_identity_assertion"),
        allowed=("config_patch", "admin_approver", "admin_identity_assertion", "change_reason", "session_id", "trace_id"),
    )


def _rotate_secret_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    return _required_kwargs(
        body,
        required=("secret_kind", "admin_approver", "admin_identity_assertion"),
        allowed=(
            "secret_kind",
            "admin_approver",
            "admin_identity_assertion",
            "new_secret_value",
            "new_secret_ref",
            "new_key_id",
            "change_reason",
            "session_id",
            "trace_id",
        ),
    )


def _required_kwargs(body: dict[str, Any], *, required: tuple[str, ...], allowed: tuple[str, ...]) -> dict[str, Any]:
    missing = [key for key in required if key not in body]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")
    return {key: body[key] for key in allowed if key in body}


def _parse_request_target(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(path)
    route = parsed.path.rstrip("/") or "/"
    return route, parse_qs(parsed.query, keep_blank_values=True)


def _query_text(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    if not values:
        return None
    text = values[-1].strip()
    return text or None


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    text = _query_text(query, key)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _query_bool(query: dict[str, list[str]], key: str, default: bool) -> bool:
    text = _query_text(query, key)
    if text is None:
        return default
    return text.lower() in {"1", "true", "yes", "on"}


def _health_payload(config: GatewayConfig) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": GATEWAY_SCHEMA_VERSION,
        "service": "tmp-mcp-hosted-bs-gateway",
        "host": config.host,
        "port": config.port,
        "mutating_requests_enabled": config.mutating_requests_enabled,
        "options": config.options.to_public_dict(include_sources=False),
    }


def _routes_payload(config: GatewayConfig) -> dict[str, Any]:
    pages = []
    if config.options.enable_approval_console:
        pages.append("/approvals")
    if config.options.enable_config_admin_console:
        pages.append("/config-admin")
    if config.options.show_gateway_settings:
        pages.append("/gateway-settings")
    read_api = ["/healthz", "/api/gateway/options"]
    if config.options.show_api_index:
        read_api.append("/api/routes")
    if config.options.enable_read_apis:
        if config.options.enable_approval_console:
            read_api.append("/api/approval-console")
        if config.options.enable_config_admin_console:
            read_api.append("/api/config-admin-console")
    mutation_api = ["/api/gateway/options/validate", "/api/gateway/options/update"]
    if config.options.enable_mutation_apis:
        mutation_api.extend(
            [
                "/api/approvals/issue-token",
                "/api/approvals/decision",
                "/api/config/validate",
                "/api/config/update",
                "/api/config/rotate-secret",
            ]
        )
    return {
        "ok": True,
        "schema_version": GATEWAY_SCHEMA_VERSION,
        "mutating_requests_enabled": config.mutating_requests_enabled,
        "routes": {
            "pages": pages,
            "read_api": read_api,
            "mutation_api": mutation_api,
        },
        "auth": {
            "mutation_header": "X-TMP-MCP-Admin-Token",
            "mutation_bearer_supported": True,
            "token_env": "TMP_MCP_GATEWAY_ADMIN_TOKEN",
        },
        "options": config.options.to_public_dict(include_sources=False),
    }


def _default_page_path(config: GatewayConfig) -> str:
    if config.options.default_page == "config-admin" and config.options.enable_config_admin_console:
        return "/config-admin"
    if config.options.default_page == "approvals" and config.options.enable_approval_console:
        return "/approvals"
    if config.options.enable_approval_console:
        return "/approvals"
    if config.options.enable_config_admin_console:
        return "/config-admin"
    if config.options.show_gateway_settings:
        return "/gateway-settings"
    return "/healthz"


def _error_payload(message: str, **details: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": GATEWAY_SCHEMA_VERSION,
        "summary": message,
        "data": details,
        "next_actions": ["Check the hosted B/S gateway route, payload and local admin token configuration."],
    }


def _create_session(username: str, user: Any, secret: str) -> dict[str, Any]:
    """Create a session token for authenticated user."""
    import hmac
    import hashlib

    now = datetime.now(timezone.utc)
    session_id = str(uuid.uuid4())
    expires_at = (now + timedelta(hours=24)).isoformat()

    session = {
        "session_id": session_id,
        "username": username,
        "approver": username,
        "roles": user.roles if hasattr(user, "roles") else ["approver"],
        "issued_at": now.isoformat(),
        "expires_at": expires_at,
    }

    payload = json.dumps(session, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    session["signature"] = signature
    return session


def _create_session_cookie(session: dict[str, Any]) -> str:
    raw = json.dumps(session, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    expires_at = str(session.get("expires_at") or "")
    cookie = SimpleCookie()
    cookie[SESSION_COOKIE_NAME] = encoded
    cookie[SESSION_COOKIE_NAME]["path"] = "/"
    cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
    if expires_at:
        cookie[SESSION_COOKIE_NAME]["expires"] = _http_cookie_expires(expires_at)
    return cookie.output(header="").strip()


def _parse_session_cookie(cookie_header: str | None) -> dict[str, Any] | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    morsel = cookie.get(SESSION_COOKIE_NAME) or cookie.get(LEGACY_SESSION_COOKIE_NAME)
    if morsel is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(morsel.value.encode("ascii"))
        session = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return session if isinstance(session, dict) else None


def _http_cookie_expires(value: str) -> str:
    try:
        expires = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _verify_session(session: dict[str, Any], secret: str) -> tuple[bool, str]:
    """Verify session token validity."""
    import hmac
    import hashlib

    if not isinstance(session, dict):
        return False, "invalid session format"

    claims = dict(session)
    signature = claims.pop("signature", None)
    if not signature:
        return False, "missing signature"

    payload = json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not secrets.compare_digest(signature, expected_signature):
        return False, "invalid signature"

    expires_at = session.get("expires_at")
    if expires_at:
        try:
            expires = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > expires:
                return False, "session expired"
        except (ValueError, TypeError):
            return False, "invalid expiration time"

    session["signature"] = signature
    return True, ""

