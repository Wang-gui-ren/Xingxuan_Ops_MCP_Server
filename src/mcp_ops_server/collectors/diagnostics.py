from __future__ import annotations

import hashlib
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psutil

from mcp_ops_server.branding import HTTP_USER_AGENT
from mcp_ops_server.collectors.disk import collect_disk_summary, find_large_files
from mcp_ops_server.collectors.network import collect_listening_ports
from mcp_ops_server.collectors.processes import collect_top_processes
from mcp_ops_server.collectors.services import get_service_status
from mcp_ops_server.utils.platform import current_platform, is_linux, is_windows


def _run_command(args: list[str], timeout_seconds: int = 15) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-4000:],
            "command_template": args,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": f"Command not found: {args[0]}",
            "command_template": args,
        }
    except Exception as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "command_template": args,
        }


def _safe_path(path: str) -> Path:
    if not path or any(token in path for token in ("\x00", "*", "?")):
        raise ValueError("Path must be explicit and must not contain wildcards.")
    return Path(path).expanduser().resolve()


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"http://{url}"
    return url


def _safe_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def check_network_connectivity(host: str, count: int = 3, timeout_seconds: int = 10) -> dict[str, Any]:
    count = _safe_int(count, 1, 10)
    timeout_seconds = _safe_int(timeout_seconds, 1, 60)
    if is_windows():
        args = ["ping", "-n", str(count), "-w", str(timeout_seconds * 1000), host]
    else:
        args = ["ping", "-c", str(count), "-W", str(timeout_seconds), host]
    result = _run_command(args, timeout_seconds=timeout_seconds + 5)
    return {
        "host": host,
        "platform": current_platform(),
        "reachable": result["ok"],
        "result": result,
    }


def trace_route(host: str, max_hops: int = 12, timeout_seconds: int = 20) -> dict[str, Any]:
    max_hops = _safe_int(max_hops, 1, 30)
    timeout_seconds = _safe_int(timeout_seconds, 1, 120)
    if is_windows():
        args = ["tracert", "-d", "-h", str(max_hops), host]
    else:
        command = "traceroute" if shutil.which("traceroute") else "tracepath"
        if command == "traceroute":
            args = [command, "-n", "-m", str(max_hops), host]
        else:
            args = [command, "-m", str(max_hops), host]
    result = _run_command(args, timeout_seconds=timeout_seconds)
    return {
        "host": host,
        "platform": current_platform(),
        "result": result,
    }


def resolve_dns(host: str, timeout_seconds: int = 5) -> dict[str, Any]:
    started = time.time()
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_seconds)
    try:
        infos = socket.getaddrinfo(host, None)
        addresses = sorted({item[4][0] for item in infos})
        return {
            "host": host,
            "resolved": bool(addresses),
            "addresses": addresses,
            "duration_ms": round((time.time() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "host": host,
            "resolved": False,
            "addresses": [],
            "error": str(exc),
            "duration_ms": round((time.time() - started) * 1000, 2),
        }
    finally:
        socket.setdefaulttimeout(previous_timeout)


def check_http_endpoint(url: str, timeout_seconds: int = 10) -> dict[str, Any]:
    timeout_seconds = _safe_int(timeout_seconds, 1, 60)
    normalized_url = _normalize_url(url)
    started = time.time()
    request = Request(
        normalized_url,
        headers={"User-Agent": HTTP_USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(512)
            return {
                "url": normalized_url,
                "ok": 200 <= response.status < 400,
                "status_code": response.status,
                "reason": response.reason,
                "duration_ms": round((time.time() - started) * 1000, 2),
                "headers": dict(response.headers.items()),
                "body_preview": body.decode("utf-8", errors="replace"),
            }
    except HTTPError as exc:
        body = exc.read(512) if hasattr(exc, "read") else b""
        return {
            "url": normalized_url,
            "ok": False,
            "status_code": exc.code,
            "reason": exc.reason,
            "duration_ms": round((time.time() - started) * 1000, 2),
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body_preview": body.decode("utf-8", errors="replace"),
        }
    except URLError as exc:
        return {
            "url": normalized_url,
            "ok": False,
            "status_code": None,
            "reason": str(exc.reason),
            "duration_ms": round((time.time() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "url": normalized_url,
            "ok": False,
            "status_code": None,
            "reason": str(exc),
            "duration_ms": round((time.time() - started) * 1000, 2),
        }


def get_file_stat(path: str, include_hash: bool = False) -> dict[str, Any]:
    file_path = _safe_path(path)
    if not file_path.exists():
        return {"path": str(file_path), "exists": False}
    stat_result = file_path.stat()
    data: dict[str, Any] = {
        "path": str(file_path),
        "exists": True,
        "is_file": file_path.is_file(),
        "is_dir": file_path.is_dir(),
        "is_symlink": file_path.is_symlink(),
        "size_bytes": stat_result.st_size,
        "modified_time": stat_result.st_mtime,
        "modified_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat_result.st_mtime)),
        "mode_octal": oct(stat_result.st_mode & 0o777),
    }
    if hasattr(stat_result, "st_uid"):
        data["uid"] = stat_result.st_uid
    if hasattr(stat_result, "st_gid"):
        data["gid"] = stat_result.st_gid
    if include_hash and file_path.is_file() and stat_result.st_size <= 128 * 1024 * 1024:
        digest = hashlib.sha256()
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        data["sha256"] = digest.hexdigest()
    elif include_hash and stat_result.st_size > 128 * 1024 * 1024:
        data["hash_skipped"] = "File is larger than 128MB."
    return data


def read_log_excerpt(
    path: str,
    lines: int = 100,
    keyword: str | None = None,
    max_bytes: int = 1024 * 1024,
) -> dict[str, Any]:
    lines = _safe_int(lines, 1, 1000)
    max_bytes = _safe_int(max_bytes, 4096, 5 * 1024 * 1024)
    file_path = _safe_path(path)
    if not file_path.exists() or not file_path.is_file():
        return {
            "path": str(file_path),
            "ok": False,
            "error": "Log path does not exist or is not a file.",
            "lines": [],
        }
    size = file_path.stat().st_size
    with file_path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(max(0, size - max_bytes))
        raw = fh.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    rows = text.splitlines()
    if keyword:
        rows = [row for row in rows if keyword.lower() in row.lower()]
    selected = rows[-lines:]
    return {
        "path": str(file_path),
        "ok": True,
        "size_bytes": size,
        "truncated_from_tail": size > max_bytes,
        "keyword": keyword,
        "line_count": len(selected),
        "lines": selected,
    }


def collect_network_connections(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = _safe_int(limit, 1, 500)
    status_filter = status.upper() if status else None
    rows: list[dict[str, Any]] = []
    for conn in psutil.net_connections(kind="inet"):
        try:
            if status_filter and conn.status.upper() != status_filter:
                continue
            process_name = None
            if conn.pid:
                try:
                    process_name = psutil.Process(conn.pid).name()
                except Exception:
                    process_name = None
            rows.append(
                {
                    "fd": conn.fd,
                    "family": str(conn.family).replace("AddressFamily.", ""),
                    "type": str(conn.type).replace("SocketKind.", ""),
                    "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                    "remote_address": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "",
                    "status": conn.status,
                    "pid": conn.pid,
                    "process_name": process_name,
                }
            )
        except Exception:
            continue
    return rows[:limit]


def list_system_services(limit: int = 80) -> dict[str, Any]:
    limit = _safe_int(limit, 1, 300)
    if is_windows():
        result = _run_command(["sc", "query", "type=", "service", "state=", "all"], timeout_seconds=20)
    elif is_linux():
        result = _run_command(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            timeout_seconds=20,
        )
    else:
        return {
            "supported": False,
            "platform": current_platform(),
            "services": [],
            "summary": "Unsupported platform for service listing.",
        }
    lines = result.get("stdout", "").splitlines()[:limit]
    return {
        "supported": True,
        "platform": current_platform(),
        "result": result,
        "line_count": len(lines),
        "lines": lines,
    }


def get_journal_events(
    unit: str | None = None,
    priority: str = "warning",
    lines: int = 80,
    since: str = "24 hours ago",
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """读取 Linux systemd journal 事件。

    Windows 或非 systemd 环境会返回结构化 unsupported，而不是抛异常。
    """
    lines = _safe_int(lines, 1, 500)
    timeout_seconds = _safe_int(timeout_seconds, 1, 60)
    if not is_linux():
        return {
            "supported": False,
            "platform": current_platform(),
            "reason": "journalctl is only supported on Linux systemd hosts.",
            "events": [],
        }
    if not shutil.which("journalctl"):
        return {
            "supported": False,
            "platform": current_platform(),
            "reason": "journalctl command was not found.",
            "events": [],
        }

    args = [
        "journalctl",
        "--no-pager",
        "--output=short-iso",
        "--since",
        since,
        "-p",
        priority,
        "-n",
        str(lines),
    ]
    if unit:
        args.extend(["-u", unit])
    result = _run_command(args, timeout_seconds=timeout_seconds)
    events = result.get("stdout", "").splitlines()[-lines:]
    return {
        "supported": True,
        "platform": current_platform(),
        "unit": unit,
        "priority": priority,
        "since": since,
        "line_count": len(events),
        "events": events,
        "result": result,
    }


def detect_large_logs(
    root_path: str,
    min_size_mb: int = 100,
    limit: int = 20,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """识别大日志文件，并标注是否落在敏感业务目录。

    该工具只做元信息扫描，不读取日志正文，适合“磁盘满 -> 日志膨胀”场景。
    """
    candidates = find_large_files(
        root_path,
        min_size_mb=min_size_mb,
        limit=max(limit * 3, limit),
        timeout_seconds=timeout_seconds,
    )
    extensions = {".log", ".out", ".err", ".trace", ".audit"}
    keyword_hits = ("log", "logs", "journal", "audit", "mysql", "postgres", "redis", "nginx", "apache")
    sensitive_keywords = ("mysql", "postgres", "postgresql", "mariadb", "oracle", "redis", "etcd", "kube", "docker")

    logs: list[dict[str, Any]] = []
    for item in candidates.get("files", []):
        path_text = item.get("path", "")
        lower = path_text.lower()
        suffix = Path(path_text).suffix.lower()
        looks_like_log = suffix in extensions or any(keyword in lower for keyword in keyword_hits)
        if not looks_like_log:
            continue
        annotated = dict(item)
        annotated["looks_like_log"] = True
        annotated["sensitive_hint"] = next((keyword for keyword in sensitive_keywords if keyword in lower), None)
        annotated["risk_note"] = (
            "Potential business or database log; do not delete directly."
            if annotated["sensitive_hint"]
            else "Classify before cleanup; prefer archive, rotate, or truncate template."
        )
        logs.append(annotated)
        if len(logs) >= limit:
            break

    return {
        "root_path": candidates.get("root_path", str(Path(root_path).expanduser())),
        "min_size_mb": min_size_mb,
        "limit": limit,
        "partial": candidates.get("partial", False),
        "scan": {
            "files_scanned": candidates.get("files_scanned", 0),
            "dirs_scanned": candidates.get("dirs_scanned", 0),
            "dirs_skipped": candidates.get("dirs_skipped", 0),
            "errors": candidates.get("errors", 0),
            "duration_ms": candidates.get("duration_ms"),
            "stop_reason": candidates.get("stop_reason"),
        },
        "logs": logs,
    }


def check_platform_compatibility() -> dict[str, Any]:
    """检查当前主机对比赛目标平台和常用运维工具的兼容情况。"""
    os_release: dict[str, str] = {}
    if is_linux() and Path("/etc/os-release").exists():
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os_release[key] = value.strip().strip('"')

    command_groups = {
        "base": ["python", "pip"],
        "linux_ops": ["systemctl", "journalctl", "ss", "lsof", "df", "du"],
        "network": ["ping", "traceroute", "tracepath", "curl"],
        "firewall": ["firewall-cmd", "iptables", "nft"],
        "windows_ops": ["powershell", "sc", "winget"],
    }
    commands = {
        group: {command: bool(shutil.which(command)) for command in commands}
        for group, commands in command_groups.items()
    }
    machine = platform.machine()
    is_loongarch = machine.lower() in {"loongarch64", "loongarch"}
    is_kylin = any("kylin" in value.lower() or "麒麟" in value for value in os_release.values())
    warnings: list[str] = []
    if is_linux() and not commands["linux_ops"]["journalctl"]:
        warnings.append("journalctl is missing; systemd journal diagnostics will be unavailable.")
    if is_linux() and not (commands["linux_ops"]["ss"] or commands["linux_ops"]["lsof"]):
        warnings.append("ss/lsof are missing; deep port ownership diagnostics may be limited.")
    if is_linux() and not is_kylin:
        warnings.append("Current Linux distribution is not detected as Kylin; verify target deployment separately.")
    if not is_loongarch:
        warnings.append("CPU architecture is not LoongArch; competition target compatibility still needs on-target validation.")

    return {
        "platform": current_platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": machine,
        "python_version": platform.python_version(),
        "is_linux": is_linux(),
        "is_windows": is_windows(),
        "is_kylin": is_kylin,
        "is_loongarch": is_loongarch,
        "os_release": os_release,
        "commands": commands,
        "warnings": warnings,
    }


def collect_resource_snapshot() -> dict[str, Any]:
    return {
        "platform": current_platform(),
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "loadavg": os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0),
        "memory": dict(psutil.virtual_memory()._asdict()),
        "swap": dict(psutil.swap_memory()._asdict()),
        "disk": collect_disk_summary(),
    }


def _parse_endpoint(url: str, host: str | None, port: int | None) -> tuple[str, str, int]:
    normalized_url = _normalize_url(url)
    parsed = urlparse(normalized_url)
    endpoint_host = host or parsed.hostname or url
    endpoint_port = port or parsed.port or (443 if parsed.scheme == "https" else 80)
    return normalized_url, endpoint_host, endpoint_port


def diagnose_website_down(
    url: str,
    host: str | None = None,
    port: int | None = None,
    service: str | None = None,
    log_path: str | None = None,
    include_trace: bool = False,
) -> dict[str, Any]:
    normalized_url, endpoint_host, endpoint_port = _parse_endpoint(url, host, port)
    steps: list[dict[str, Any]] = []

    dns = resolve_dns(endpoint_host)
    steps.append({"name": "dns_resolution", "ok": dns.get("resolved", False), "data": dns})

    ping = check_network_connectivity(endpoint_host, count=2)
    steps.append({"name": "network_connectivity", "ok": ping.get("reachable", False), "data": ping})

    if include_trace:
        trace = trace_route(endpoint_host)
        steps.append({"name": "route_trace", "ok": trace.get("result", {}).get("ok", False), "data": trace})

    http = check_http_endpoint(normalized_url)
    steps.append({"name": "http_probe", "ok": http.get("ok", False), "data": http})

    ports = collect_listening_ports(limit=120)
    matched_ports = [item for item in ports if item.get("local_address", "").endswith(f":{endpoint_port}")]
    steps.append(
        {
            "name": "local_listening_port",
            "ok": bool(matched_ports),
            "data": {"port": endpoint_port, "matches": matched_ports[:10]},
        }
    )

    if service:
        service_status = get_service_status(service)
        steps.append(
            {
                "name": "service_status",
                "ok": service_status.get("exit_code") == 0,
                "data": service_status,
            }
        )

    if log_path:
        log_excerpt = read_log_excerpt(log_path, lines=80, keyword="error")
        steps.append({"name": "error_log_excerpt", "ok": log_excerpt.get("ok", False), "data": log_excerpt})

    resources = collect_resource_snapshot()
    steps.append({"name": "resource_snapshot", "ok": True, "data": resources})

    next_actions = [
        "If DNS failed, verify domain records or local hosts configuration.",
        "If HTTP failed but port is listening, inspect application logs and reverse proxy configuration.",
        "If the port is not listening, check service status and recent startup errors.",
        "If resources are saturated, prioritize CPU, memory, and disk remediation before restarting services.",
    ]
    return {
        "scenario": "website_down",
        "target": {"url": normalized_url, "host": endpoint_host, "port": endpoint_port, "service": service},
        "steps": steps,
        "next_actions": next_actions,
    }


def diagnose_high_cpu(limit: int = 10) -> dict[str, Any]:
    limit = _safe_int(limit, 1, 50)
    resources = collect_resource_snapshot()
    top_processes = collect_top_processes(limit=limit)
    suspect_processes = [
        item
        for item in top_processes
        if (item.get("cpu_percent") or 0.0) >= 50 or (item.get("memory_percent") or 0.0) >= 20
    ]
    return {
        "scenario": "high_cpu",
        "steps": [
            {"name": "resource_snapshot", "ok": True, "data": resources},
            {"name": "top_processes", "ok": True, "data": {"processes": top_processes}},
            {"name": "suspect_processes", "ok": True, "data": {"processes": suspect_processes}},
        ],
        "next_actions": [
            "Confirm whether the top process belongs to a managed service before stopping it.",
            "For Java processes, collect thread dump with a fixed template before restart.",
            "If CPU pressure is transient, observe multiple samples before taking action.",
        ],
    }


def diagnose_disk_full(root_path: str = ".", min_size_mb: int = 100, limit: int = 20) -> dict[str, Any]:
    min_size_mb = _safe_int(min_size_mb, 1, 1024 * 1024)
    limit = _safe_int(limit, 1, 100)
    disks = collect_disk_summary()
    pressure = [item for item in disks if item.get("percent", 0) >= 80]
    large_files = find_large_files(root_path, min_size_mb=min_size_mb, limit=limit)
    return {
        "scenario": "disk_full",
        "steps": [
            {"name": "disk_usage", "ok": True, "data": {"partitions": disks, "pressure": pressure}},
            {
                "name": "large_file_scan",
                "ok": True,
                "data": large_files,
            },
        ],
        "next_actions": [
            "Classify large files before cleanup: application logs, database logs, cache, backup, or unknown.",
            "Prefer archive/quarantine/truncate templates instead of direct deletion.",
            "If database logs are large, verify backup and replication status before cleanup.",
        ],
    }


def diagnose_port_conflict(port: int, limit: int = 120) -> dict[str, Any]:
    port = _safe_int(port, 1, 65535)
    ports = collect_listening_ports(limit=limit)
    matches = [item for item in ports if item.get("local_address", "").endswith(f":{port}")]
    return {
        "scenario": "port_conflict",
        "target": {"port": port},
        "steps": [
            {"name": "listening_port_lookup", "ok": bool(matches), "data": {"matches": matches, "all_ports_sample": ports[:20]}},
        ],
        "next_actions": [
            "If an unexpected process owns the port, inspect process path and service ownership.",
            "Prefer changing application config or stopping the managed service instead of killing a PID directly.",
        ],
    }


def diagnose_service_issue(service: str, log_path: str | None = None) -> dict[str, Any]:
    status = get_service_status(service)
    steps: list[dict[str, Any]] = [
        {"name": "service_status", "ok": status.get("exit_code") == 0, "data": status},
        {"name": "resource_snapshot", "ok": True, "data": collect_resource_snapshot()},
    ]
    if log_path:
        steps.append({"name": "service_log_excerpt", "ok": True, "data": read_log_excerpt(log_path, lines=100, keyword="error")})
    return {
        "scenario": "service_issue",
        "target": {"service": service, "log_path": log_path},
        "steps": steps,
        "next_actions": [
            "Review service logs before restart.",
            "If config changed recently, validate config syntax before reload.",
            "Use request_restart_service with dry_run=true before any real restart.",
        ],
    }


def run_troubleshooting_pipeline(
    scenario: str,
    url: str | None = None,
    host: str | None = None,
    port: int | None = None,
    service: str | None = None,
    log_path: str | None = None,
    root_path: str = ".",
    min_size_mb: int = 100,
    limit: int = 20,
) -> dict[str, Any]:
    normalized = scenario.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"website_down", "web_down", "site_down", "网站打不开"}:
        if not url and not host:
            raise ValueError("website_down pipeline requires url or host.")
        return diagnose_website_down(url or host or "", host=host, port=port, service=service, log_path=log_path)
    if normalized in {"high_cpu", "cpu_high", "cpu_100", "cpu占用高"}:
        return diagnose_high_cpu(limit=limit)
    if normalized in {"disk_full", "disk_pressure", "磁盘满", "磁盘空间爆满"}:
        return diagnose_disk_full(root_path=root_path, min_size_mb=min_size_mb, limit=limit)
    if normalized in {"port_conflict", "端口冲突"}:
        if port is None:
            raise ValueError("port_conflict pipeline requires port.")
        return diagnose_port_conflict(port=port, limit=max(limit, 50))
    if normalized in {"service_issue", "service_down", "服务异常"}:
        if not service:
            raise ValueError("service_issue pipeline requires service.")
        return diagnose_service_issue(service=service, log_path=log_path)
    raise ValueError(f"Unsupported troubleshooting scenario: {scenario}")
