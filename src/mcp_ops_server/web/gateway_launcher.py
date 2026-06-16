from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from mcp_ops_server.branding import (
    HOSTED_GATEWAY_SERVICE,
    LEGACY_HOSTED_GATEWAY_SERVICE,
    PRODUCT_NAME,
    get_prefixed_env,
)
from mcp_ops_server.config import WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV, default_web_gateway_options_config_path


DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 8765
GATEWAY_HEALTH_SERVICE = HOSTED_GATEWAY_SERVICE
GATEWAY_SCHEMA_VERSION = "hosted-bs-gateway-v1"

_LOCK = Lock()
_STARTED_PROCESSES: dict[tuple[str, int, str], subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class GatewayLaunchResult:
    ok: bool
    started: bool
    reused_existing: bool
    host: str
    port: int
    base_url: str
    page_url: str
    routes_url: str
    health_url: str
    page: str
    options_file: str
    process_id: int | None = None
    health: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "started": self.started,
            "reused_existing": self.reused_existing,
            "host": self.host,
            "port": self.port,
            "base_url": self.base_url,
            "page_url": self.page_url,
            "routes_url": self.routes_url,
            "health_url": self.health_url,
            "page": self.page,
            "options_file": self.options_file,
            "process_id": self.process_id,
            "health": self.health,
            "warnings": list(self.warnings),
            "error": self.error,
        }


def ensure_hosted_gateway(
    *,
    host: str | None = None,
    port: int | None = None,
    page: str = "approvals",
    approval_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    options_file: str | Path | None = None,
    startup_timeout_seconds: float = 8.0,
    allow_port_fallback: bool = True,
) -> GatewayLaunchResult:
    """Start or reuse the local hosted B/S gateway without importing gateway.py.

    This module is used by MCP tools. It launches the gateway in a child Python
    process to avoid recursive imports between the MCP tool registry and the HTTP
    gateway, which itself registers MCP tools for route handlers.
    """

    safe_host = _clean_host(host)
    safe_port = _clean_port(port)
    safe_page = _clean_page(page)
    safe_options_file = _resolve_options_file(options_file)
    warnings: list[str] = []

    with _LOCK:
        for candidate_port in _candidate_ports(safe_port, allow_port_fallback=allow_port_fallback):
            health = _read_gateway_health(safe_host, candidate_port)
            if _health_is_supported_gateway(health):
                return _launch_result(
                    ok=True,
                    started=False,
                    reused_existing=True,
                    host=safe_host,
                    port=candidate_port,
                    page=safe_page,
                    options_file=safe_options_file,
                    approval_id=approval_id,
                    status=status,
                    limit=limit,
                    health=health,
                    warnings=warnings,
                )

            process_key = (safe_host, candidate_port, safe_options_file)
            process = _STARTED_PROCESSES.get(process_key)
            if process is not None and process.poll() is None:
                health = _wait_for_gateway_health(safe_host, candidate_port, startup_timeout_seconds)
                if _health_is_supported_gateway(health):
                    return _launch_result(
                        ok=True,
                        started=False,
                        reused_existing=True,
                        host=safe_host,
                        port=candidate_port,
                        page=safe_page,
                        options_file=safe_options_file,
                        approval_id=approval_id,
                        status=status,
                        limit=limit,
                        process_id=process.pid,
                        health=health,
                        warnings=warnings,
                    )

            if _tcp_port_is_open(safe_host, candidate_port):
                warnings.append(f"port {candidate_port} is already in use by a non {PRODUCT_NAME} gateway")
                continue

            process = _spawn_gateway_process(safe_host, candidate_port, safe_options_file)
            _STARTED_PROCESSES[process_key] = process
            health = _wait_for_gateway_health(safe_host, candidate_port, startup_timeout_seconds)
            if _health_is_supported_gateway(health):
                return _launch_result(
                    ok=True,
                    started=True,
                    reused_existing=False,
                    host=safe_host,
                    port=candidate_port,
                    page=safe_page,
                    options_file=safe_options_file,
                    approval_id=approval_id,
                    status=status,
                    limit=limit,
                    process_id=process.pid,
                    health=health,
                    warnings=warnings,
                )

            error = _process_error(process) or f"gateway did not become healthy on {safe_host}:{candidate_port}"
            _terminate_process(process)
            _STARTED_PROCESSES.pop(process_key, None)
            warnings.append(error)

    return _launch_result(
        ok=False,
        started=False,
        reused_existing=False,
        host=safe_host,
        port=safe_port,
        page=safe_page,
        options_file=safe_options_file,
        approval_id=approval_id,
        status=status,
        limit=limit,
        health={},
        warnings=warnings,
        error="unable to start or reuse hosted B/S gateway",
    )


def shutdown_spawned_gateways() -> None:
    """Terminate gateway child processes started by this process.

    This is intentionally not registered as an MCP tool. It exists for local
    verification scripts and process cleanup only.
    """

    with _LOCK:
        processes = list(_STARTED_PROCESSES.values())
        _STARTED_PROCESSES.clear()
    for process in processes:
        _terminate_process(process)


atexit.register(shutdown_spawned_gateways)


def _launch_result(
    *,
    ok: bool,
    started: bool,
    reused_existing: bool,
    host: str,
    port: int,
    page: str,
    options_file: str,
    approval_id: str | None,
    status: str | None,
    limit: int | None,
    health: dict[str, Any],
    process_id: int | None = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> GatewayLaunchResult:
    base_url = f"http://{host}:{port}"
    page_path = f"/{page}"
    query: dict[str, str] = {}
    if approval_id:
        query["approval_id"] = approval_id
    if status:
        query["status"] = status
    if limit is not None:
        query["limit"] = str(max(1, int(limit)))
    if query:
        page_path = f"{page_path}?{urlencode(query)}"
    return GatewayLaunchResult(
        ok=ok,
        started=started,
        reused_existing=reused_existing,
        host=host,
        port=port,
        base_url=base_url,
        page_url=f"{base_url}{page_path}",
        routes_url=f"{base_url}/api/routes",
        health_url=f"{base_url}/healthz",
        page=page,
        options_file=options_file,
        process_id=process_id,
        health=health,
        warnings=tuple(warnings or ()),
        error=error,
    )


def _spawn_gateway_process(host: str, port: int, options_file: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = _prepend_path(env.get("PYTHONPATH"), src_path)
    env.setdefault(WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV, options_file)
    env.setdefault("XINGXUAN_MCP_GATEWAY_QUIET", "true")
    env.setdefault("TMP_MCP_GATEWAY_QUIET", env["XINGXUAN_MCP_GATEWAY_QUIET"])
    command = [
        sys.executable,
        "-m",
        "mcp_ops_server.web_gateway",
        "--host",
        host,
        "--port",
        str(port),
        "--options-file",
        options_file,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
    )


def _read_gateway_health(host: str, port: int) -> dict[str, Any] | None:
    try:
        with urlopen(f"http://{host}:{port}/healthz", timeout=1.0) as response:
            raw = response.read().decode("utf-8")
    except (OSError, URLError, TimeoutError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _wait_for_gateway_health(host: str, port: int, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    while time.monotonic() < deadline:
        health = _read_gateway_health(host, port)
        if _health_is_supported_gateway(health):
            return health
        time.sleep(0.15)
    return None


def _health_is_supported_gateway(health: dict[str, Any] | None) -> bool:
    if not isinstance(health, dict):
        return False
    return (
        health.get("ok") is True
        and health.get("schema_version") == GATEWAY_SCHEMA_VERSION
        and health.get("service") in {GATEWAY_HEALTH_SERVICE, LEGACY_HOSTED_GATEWAY_SERVICE}
    )


def _tcp_port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _candidate_ports(port: int, *, allow_port_fallback: bool) -> list[int]:
    if not allow_port_fallback:
        return [port]
    return [port + offset for offset in range(0, 10)]


def _clean_host(host: str | None) -> str:
    text = str(host or DEFAULT_GATEWAY_HOST).strip()
    return text or DEFAULT_GATEWAY_HOST


def _clean_port(port: int | None) -> int:
    try:
        value = int(port if port is not None else get_prefixed_env("TMP_MCP_GATEWAY_PORT") or DEFAULT_GATEWAY_PORT)
    except (TypeError, ValueError):
        value = DEFAULT_GATEWAY_PORT
    if value < 1 or value > 65535:
        return DEFAULT_GATEWAY_PORT
    return value


def _clean_page(page: str) -> str:
    text = str(page or "approvals").strip().strip("/")
    if text in {"approvals", "config-admin", "gateway-settings"}:
        return text
    return "approvals"


def _resolve_options_file(options_file: str | Path | None) -> str:
    if options_file:
        return str(Path(options_file))
    return str(default_web_gateway_options_config_path())


def _prepend_path(current: str | None, path: str) -> str:
    parts = [item for item in (current or "").split(os.pathsep) if item]
    if path not in parts:
        parts.insert(0, path)
    return os.pathsep.join(parts)


def _process_error(process: subprocess.Popen[bytes]) -> str | None:
    return_code = process.poll()
    if return_code is None:
        return None
    return f"gateway process exited early with code {return_code}"


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
