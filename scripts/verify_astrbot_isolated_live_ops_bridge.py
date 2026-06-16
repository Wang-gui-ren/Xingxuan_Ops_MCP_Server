from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SYNC_PLUGIN_FILES = ("main.py", "intent_parser.py", "metadata.yaml", "README.md")


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2] / "tmp_astrbot"
    parser = argparse.ArgumentParser(
        description="Launch an isolated AstrBot instance and run live deterministic ops bridge verification.",
    )
    parser.add_argument(
        "--astrbot-project-root",
        default=str(project_root),
        help="Path to the AstrBot project root containing main.py.",
    )
    parser.add_argument(
        "--python-exe",
        default=sys_executable_fallback(),
        help="Python executable used to launch AstrBot.",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=int,
        default=90,
        help="How long to wait for the isolated AstrBot dashboard to become ready.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=45,
        help="HTTP timeout for dashboard requests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks: list[dict[str, Any]] = []

    astrbot_root = Path(args.astrbot_project_root).resolve()
    check(checks, (astrbot_root / "main.py").exists(), "astrbot project root looks valid")
    if not (astrbot_root / "main.py").exists():
        _finish(checks)
        return

    with tempfile.TemporaryDirectory(prefix="astrbot_live_bridge_root_") as tmp:
        temp_root = Path(tmp)
        data_dir = temp_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        source_cmd_config = astrbot_root / "data" / "cmd_config.json"
        source_mcp_config = astrbot_root / "data" / "mcp_server.json"
        source_dist = astrbot_root / "data" / "dist"
        plugin_source = Path(__file__).resolve().parents[1] / "integrations" / "astrbot_filesystem_command"
        plugin_installed = data_dir / "plugins" / "astrbot_plugin_xingxuan_mcp_filesystem"

        check(checks, source_cmd_config.exists(), "source cmd_config exists")
        check(checks, source_mcp_config.exists(), "source mcp_server exists")
        check(checks, source_dist.exists(), "source dist exists")
        check(checks, plugin_source.exists(), "bridge source plugin exists")
        if not all([source_cmd_config.exists(), source_mcp_config.exists(), source_dist.exists(), plugin_source.exists()]):
            _finish(checks)
            return

        cmd_config = json.loads(source_cmd_config.read_text(encoding="utf-8-sig"))
        cmd_config.setdefault("dashboard", {})
        cmd_config["dashboard"]["host"] = "127.0.0.1"
        cmd_config["dashboard"]["enable"] = True
        cmd_config["dashboard"]["disable_access_log"] = True
        cmd_config_path = data_dir / "cmd_config.json"
        cmd_config_path.write_text(json.dumps(cmd_config, ensure_ascii=False, indent=2), encoding="utf-8")

        shutil.copy2(source_mcp_config, data_dir / "mcp_server.json")

        plugin_installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(plugin_source, plugin_installed, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        check(checks, plugin_installed.exists(), "bridge plugin copied into isolated root")

        for name in SYNC_PLUGIN_FILES:
            source_hash = _sha256(plugin_source / name)
            installed_hash = _sha256(plugin_installed / name)
            check(checks, source_hash == installed_hash, f"{name}: isolated plugin matches source")

        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        stdout_log = temp_root / "astrbot_stdout.log"
        stderr_log = temp_root / "astrbot_stderr.log"

        env = os.environ.copy()
        env["ASTRBOT_ROOT"] = str(temp_root)
        env["DASHBOARD_HOST"] = "127.0.0.1"
        env["DASHBOARD_PORT"] = str(port)
        env["PYTHONUNBUFFERED"] = "1"

        stdout_handle = stdout_log.open("w", encoding="utf-8")
        stderr_handle = stderr_log.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [args.python_exe, "main.py", "--webui-dir", str(source_dist)],
            cwd=str(astrbot_root),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )

        try:
            ready = _wait_for_dashboard_ready(base_url, timeout_seconds=args.startup_timeout_seconds)
            check(checks, ready, "isolated AstrBot dashboard became ready")
            if not ready:
                _attach_process_diagnostics(checks, stdout_log, stderr_log)
                _finish(checks)
                return

            username = str(cmd_config["dashboard"].get("username") or "").strip()
            secret = str(cmd_config["dashboard"].get("jwt_secret") or "").strip()
            check(checks, bool(username), "isolated dashboard username exists")
            check(checks, bool(secret), "isolated dashboard jwt_secret exists")
            if not username or not secret:
                _attach_process_diagnostics(checks, stdout_log, stderr_log)
                _finish(checks)
                return

            token = _build_dashboard_jwt(username=username, secret=secret)
            auth_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            reload_payload = _json_request(
                f"{base_url}/api/plugin/reload",
                method="POST",
                headers=auth_headers,
                data={"name": "astrbot_plugin_xingxuan_mcp_filesystem"},
                timeout_seconds=args.request_timeout_seconds,
            )
            check(checks, reload_payload.get("status") == "ok", "isolated plugin reload succeeded")

            log_file = temp_root / "logs" / "app.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("isolated live log cleanup verification\n", encoding="utf-8")

            cases = [
                {
                    "name": "isolated_live_create_directory",
                    "message": f"在 {temp_root} 这个文件夹新建一个空文件夹：名字叫 live_test1",
                    "expected_markers": ["request_create_directory", "approval_scope_hash", "execute_after_approval"],
                    "expected_tool_log": "tool=request_create_directory",
                },
                {
                    "name": "isolated_live_restart_service",
                    "message": "重启 Spooler 服务",
                    "expected_markers": ["request_restart_service", "approval_scope_hash", "execute_after_approval"],
                    "expected_tool_log": "tool=request_restart_service",
                },
                {
                    "name": "isolated_live_network_policy",
                    "message": "开放 tcp 8080 端口",
                    "expected_markers": ["request_network_policy_change", "approval_scope_hash", "execute_after_approval"],
                    "expected_tool_log": "tool=request_network_policy_change",
                },
                {
                    "name": "isolated_live_log_cleanup",
                    "message": f"隔离 {log_file}",
                    "expected_markers": ["request_log_cleanup", "approval_scope_hash", "execute_after_approval"],
                    "expected_tool_log": "tool=request_log_cleanup",
                },
                {
                    "name": "isolated_live_remote_linux_profile",
                    "message": "查看远程 linux 服务器 192.168.1.20 用户 ops 端口 22 主机画像",
                    "expected_markers": ["Unable to collect remote host profile", "\"mode\": \"unavailable\"", "\"success\": false"],
                    "expected_tool_log": "tool=get_host_profile_tool",
                },
                {
                    "name": "isolated_live_remote_linux_restart_service",
                    "message": "重启远程 linux 服务器 192.168.1.20 上的 nginx 服务 用户 ops 端口 22",
                    "expected_markers": [
                        "\"mode\": \"reference_only\"",
                        "\"transport\": \"ssh\"",
                        "\"reference_request\"",
                        "\"reference_preflight\"",
                    ],
                    "expected_tool_log": "tool=request_restart_service",
                },
                {
                    "name": "isolated_live_remote_windows_restart_service",
                    "message": "重启远程 windows 服务器 win-server-01 上的 Spooler 服务 账号 admin 端口 5985",
                    "expected_markers": [
                        "\"mode\": \"reference_only\"",
                        "\"transport\": \"winrm\"",
                        "\"reference_request\"",
                        "\"reference_preflight\"",
                    ],
                    "expected_tool_log": "tool=request_restart_service",
                },
            ]

            complex_cases = [
                {
                    "name": "isolated_complex_linux_analysis",
                    "message": "帮我看看 nginx 为什么不可用",
                },
                {
                    "name": "isolated_complex_windows_analysis",
                    "message": "分析这台 Windows 服务器 CPU 为什么飙高",
                },
            ]

            for case in cases:
                session_payload = _json_request(
                    f"{base_url}/api/chat/new_session?platform_id=webchat",
                    method="GET",
                    headers={"Authorization": auth_headers["Authorization"]},
                    data=None,
                    timeout_seconds=args.request_timeout_seconds,
                )
                session_id = (
                    session_payload.get("data", {}).get("session_id")
                    if isinstance(session_payload.get("data"), dict)
                    else None
                )
                check(checks, isinstance(session_id, str) and bool(session_id), f"{case['name']}: new session created")
                if not isinstance(session_id, str) or not session_id:
                    continue

                events = _chat_send_and_collect_events(
                    f"{base_url}/api/chat/send",
                    headers=auth_headers,
                    payload={
                        "session_id": session_id,
                        "message": case["message"],
                        "enable_streaming": False,
                    },
                    timeout_seconds=args.request_timeout_seconds,
                )
                text_blob = _collect_text_blob(events)
                checks.append(
                    {
                        "name": f"{case['name']}: sse_text_preview",
                        "status": "INFO",
                        "details": text_blob[:1200],
                    }
                )
                check(checks, bool(events), f"{case['name']}: received sse events")
                check(checks, any(event.get("type") == "session_id" for event in events), f"{case['name']}: session_id event received")
                check(checks, any(event.get("type") == "message_saved" for event in events), f"{case['name']}: message_saved event received")
                check(checks, any(event.get("type") == "end" for event in events), f"{case['name']}: end event received")
                for marker in case["expected_markers"]:
                    check(checks, marker in text_blob, f"{case['name']}: marker {marker} found")

                delete_payload = _json_request(
                    f"{base_url}/api/chat/delete_session?session_id={urllib.parse.quote(session_id)}",
                    method="GET",
                    headers={"Authorization": auth_headers["Authorization"]},
                    data=None,
                    timeout_seconds=args.request_timeout_seconds,
                )
                check(checks, delete_payload.get("status") == "ok", f"{case['name']}: session deleted")

            for case in complex_cases:
                session_payload = _json_request(
                    f"{base_url}/api/chat/new_session?platform_id=webchat",
                    method="GET",
                    headers={"Authorization": auth_headers["Authorization"]},
                    data=None,
                    timeout_seconds=args.request_timeout_seconds,
                )
                session_id = (
                    session_payload.get("data", {}).get("session_id")
                    if isinstance(session_payload.get("data"), dict)
                    else None
                )
                check(checks, isinstance(session_id, str) and bool(session_id), f"{case['name']}: new session created")
                if not isinstance(session_id, str) or not session_id:
                    continue

                events = _chat_send_and_collect_events(
                    f"{base_url}/api/chat/send",
                    headers=auth_headers,
                    payload={
                        "session_id": session_id,
                        "message": case["message"],
                        "enable_streaming": False,
                    },
                    timeout_seconds=args.request_timeout_seconds,
                )
                text_blob = _collect_text_blob(events)
                checks.append(
                    {
                        "name": f"{case['name']}: sse_text_preview",
                        "status": "INFO",
                        "details": text_blob[:1200],
                    }
                )
                check(checks, bool(events), f"{case['name']}: received sse events")
                check(checks, any(event.get("type") == "session_id" for event in events), f"{case['name']}: session_id event received")
                check(checks, any(event.get("type") == "message_saved" for event in events), f"{case['name']}: message_saved event received")
                check(checks, any(event.get("type") == "end" for event in events), f"{case['name']}: end event received")
                check(
                    checks,
                    not any(marker in text_blob for marker in (
                        "request_create_directory",
                        "request_restart_service",
                        "request_network_policy_change",
                        "request_log_cleanup",
                    )),
                    f"{case['name']}: no deterministic bridge tool marker in response",
                )
                delete_payload = _json_request(
                    f"{base_url}/api/chat/delete_session?session_id={urllib.parse.quote(session_id)}",
                    method="GET",
                    headers={"Authorization": auth_headers["Authorization"]},
                    data=None,
                    timeout_seconds=args.request_timeout_seconds,
                )
                check(checks, delete_payload.get("status") == "ok", f"{case['name']}: session deleted")

            time.sleep(1.0)
            stdout_text = stdout_log.read_text(encoding="utf-8", errors="replace") if stdout_log.exists() else ""
            checks.append(
                {
                    "name": "isolated_astrbot_stdout_tail",
                    "status": "INFO",
                    "details": stdout_text[-4000:],
                }
            )
            check(checks, "星璇运维MCP deterministic ops bridge loaded." in stdout_text, "isolated logs include bridge loaded")
            for tool_log in (
                "tool=request_create_directory",
                "tool=request_restart_service",
                "tool=request_network_policy_change",
                "tool=request_log_cleanup",
                "tool=get_host_profile_tool",
            ):
                check(checks, tool_log in stdout_text, f"isolated logs include {tool_log}")
            for complex_message in (
                "帮我看看 nginx 为什么不可用",
                "分析这台 Windows 服务器 CPU 为什么飙高",
            ):
                check(
                    checks,
                    complex_message not in stdout_text,
                    f"isolated logs do not show deterministic intercept for {complex_message}",
                )

        finally:
            try:
                proc.terminate()
                proc.wait(timeout=20)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            stdout_handle.close()
            stderr_handle.close()

    _finish(checks)


def sys_executable_fallback() -> str:
    return os.environ.get("PYTHON", "") or "python"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_for_dashboard_ready(base_url: str, *, timeout_seconds: int) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{base_url}/api/auth/setup-status", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def _attach_process_diagnostics(checks: list[dict[str, Any]], stdout_log: Path, stderr_log: Path) -> None:
    if stdout_log.exists():
        checks.append(
            {
                "name": "isolated_astrbot_stdout_tail",
                "status": "INFO",
                "details": _tail_text(stdout_log),
            }
        )
    if stderr_log.exists():
        checks.append(
            {
                "name": "isolated_astrbot_stderr_tail",
                "status": "INFO",
                "details": _tail_text(stderr_log),
            }
        )


def _tail_text(path: Path, limit: int = 4000) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return text[-limit:]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_dashboard_jwt(*, username: str, secret: str, ttl_seconds: int = 1800) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"username": username, "exp": int(time.time()) + ttl_seconds}
    signing_input = ".".join((_b64url_json(header), _b64url_json(payload)))
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_bytes(signature)}"


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url_bytes(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _json_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    data: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            if isinstance(parsed, dict):
                parsed["__http_status__"] = getattr(response, "status", 200)
                return parsed
            return {"status": "error", "message": "non-dict response", "data": parsed, "__http_status__": getattr(response, "status", 200)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                parsed["__http_status__"] = exc.code
                return parsed
        except Exception:
            pass
        return {
            "status": "error",
            "message": body or str(exc),
            "data": None,
            "__http_status__": exc.code,
        }


def _chat_send_and_collect_events(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    events: list[dict[str, Any]] = []
    current_lines: list[str] = []
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        while True:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                if current_lines:
                    event = _parse_sse_event(current_lines)
                    if event is not None:
                        events.append(event)
                        if event.get("type") == "end":
                            break
                    current_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data: "):
                current_lines.append(line[6:])
    return events


def _parse_sse_event(lines: list[str]) -> dict[str, Any] | None:
    text = "\n".join(lines).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"type": "raw", "data": parsed}
    except Exception:
        return {"type": "raw_text", "data": text}


def _collect_text_blob(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        data = event.get("data")
        if isinstance(data, str):
            parts.append(data)
    return "\n".join(parts)


def _finish(checks: list[dict[str, Any]]) -> None:
    failed = [item for item in checks if item["status"] == "FAIL"]
    payload = {
        "total": len(checks),
        "passed": len([item for item in checks if item["status"] == "PASS"]),
        "failed": len(failed),
        "checks": checks,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    if failed:
        raise SystemExit(1)


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
