from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose a running AstrBot dashboard and verify whether live deterministic ops bridge testing is currently possible.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:6185",
        help="AstrBot dashboard base URL.",
    )
    parser.add_argument(
        "--cmd-config",
        default=str(Path(__file__).resolve().parents[2] / "tmp_astrbot" / "data" / "cmd_config.json"),
        help="Path to AstrBot cmd_config.json.",
    )
    parser.add_argument(
        "--plugin-name",
        default="astrbot_plugin_xingxuan_mcp_filesystem",
        help="Plugin directory name to reload.",
    )
    parser.add_argument(
        "--session-platform",
        default="webchat",
        help="Platform ID for /api/chat/new_session.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="HTTP timeout for each request.",
    )
    parser.add_argument(
        "--tries",
        type=int,
        default=3,
        help="How many times to retry live plugin reload and new_session before concluding the current running instance is unhealthy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks: list[dict[str, Any]] = []

    cmd_config = Path(args.cmd_config)
    check(checks, cmd_config.exists(), "cmd_config exists")
    if not cmd_config.exists():
        _finish(checks)
        return

    config = json.loads(cmd_config.read_text(encoding="utf-8-sig"))
    dashboard = config.get("dashboard", {})
    username = str(dashboard.get("username") or "").strip()
    jwt_secret = str(dashboard.get("jwt_secret") or "").strip()
    check(checks, bool(username), "dashboard username exists")
    check(checks, bool(jwt_secret), "dashboard jwt_secret exists")
    if not username or not jwt_secret:
        _finish(checks)
        return

    data_dir = cmd_config.parent
    db_path = data_dir / "data_v4.db"
    check(checks, db_path.exists(), "AstrBot SQLite database file exists")
    if db_path.exists():
        db_diag = _check_sqlite_health(db_path)
        check(checks, db_diag["ok"], "AstrBot SQLite file passes integrity check")
        checks.append({"name": "sqlite_integrity_check", "status": "INFO", "details": db_diag})

    setup_status = _json_request(
        f"{args.base_url.rstrip('/')}/api/auth/setup-status",
        method="GET",
        headers={},
        data=None,
        timeout_seconds=args.timeout_seconds,
    )
    check(
        checks,
        setup_status.get("__http_status__") == 200 and setup_status.get("status") == "ok",
        "dashboard setup-status endpoint reachable",
    )
    checks.append({"name": "dashboard_setup_status_payload", "status": "INFO", "details": setup_status})

    token = _build_dashboard_jwt(username=username, secret=jwt_secret)
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    reload_attempts: list[dict[str, Any]] = []
    reload_payload: dict[str, Any] = {}
    for attempt in range(1, max(1, args.tries) + 1):
        reload_payload = _json_request(
            f"{args.base_url.rstrip('/')}/api/plugin/reload",
            method="POST",
            headers=auth_headers,
            data={"name": args.plugin_name},
            timeout_seconds=args.timeout_seconds,
        )
        reload_attempts.append({"attempt": attempt, "payload": reload_payload})
        if reload_payload.get("status") == "ok":
            break
        time.sleep(1)
    check(checks, reload_payload.get("status") == "ok", "plugin reload succeeded")
    checks.append({"name": "plugin_reload_attempts", "status": "INFO", "details": reload_attempts})
    check(
        checks,
        "disk I/O error" not in json.dumps(reload_payload, ensure_ascii=False),
        "plugin reload payload has no sqlite disk I/O error",
    )

    session_attempts: list[dict[str, Any]] = []
    session_payload: dict[str, Any] = {}
    session_id = None
    for attempt in range(1, max(1, args.tries) + 1):
        session_payload = _json_request(
            f"{args.base_url.rstrip('/')}/api/chat/new_session?platform_id={urllib.parse.quote(args.session_platform)}",
            method="GET",
            headers={"Authorization": auth_headers["Authorization"]},
            data=None,
            timeout_seconds=args.timeout_seconds,
        )
        session_attempts.append({"attempt": attempt, "payload": session_payload})
        session_id = (
            session_payload.get("data", {}).get("session_id")
            if isinstance(session_payload.get("data"), dict)
            else None
        )
        if isinstance(session_id, str) and bool(session_id):
            break
        time.sleep(1)
    checks.append({"name": "chat_new_session_attempts", "status": "INFO", "details": session_attempts})
    check(checks, isinstance(session_id, str) and bool(session_id), "chat new_session succeeded")

    if isinstance(session_id, str) and session_id:
        with tempfile.TemporaryDirectory(prefix="tmp_mcp_live_bridge_") as tmp:
            log_file = Path(tmp) / "logs" / "app.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("live ops bridge log cleanup verification\n", encoding="utf-8")

            cases = [
                {
                    "name": "live_create_directory",
                    "message": "在 G:\\完整mcp 这个文件夹新建一个空文件夹：名字叫 live_test1",
                    "expected_markers": ["request_create_directory", "approval_scope_hash", "execute_after_approval"],
                },
                {
                    "name": "live_restart_service",
                    "message": "重启 Spooler 服务",
                    "expected_markers": ["request_restart_service", "approval_scope_hash", "execute_after_approval"],
                },
                {
                    "name": "live_network_policy",
                    "message": "开放 tcp 8080 端口",
                    "expected_markers": ["request_network_policy_change", "approval_scope_hash", "execute_after_approval"],
                },
                {
                    "name": "live_log_cleanup",
                    "message": f"隔离 {log_file}",
                    "expected_markers": ["request_log_cleanup", "approval_scope_hash", "execute_after_approval"],
                },
                {
                    "name": "live_remote_linux_profile",
                    "message": "查看远程 linux 服务器 192.168.1.20 用户 ops 端口 22 主机画像",
                    "expected_markers": ["Unable to collect remote host profile", "\"mode\": \"unavailable\"", "\"success\": false"],
                },
                {
                    "name": "live_remote_linux_restart_service",
                    "message": "重启远程 linux 服务器 192.168.1.20 上的 nginx 服务 用户 ops 端口 22",
                    "expected_markers": ["\"mode\": \"reference_only\"", "\"transport\": \"ssh\"", "\"reference_request\"", "\"reference_preflight\""],
                },
                {
                    "name": "live_remote_windows_restart_service",
                    "message": "重启远程 windows 服务器 win-server-01 上的 Spooler 服务 账号 admin 端口 5985",
                    "expected_markers": ["\"mode\": \"reference_only\"", "\"transport\": \"winrm\"", "\"reference_request\"", "\"reference_preflight\""],
                },
            ]
            complex_cases = [
                {
                    "name": "live_complex_linux_analysis",
                    "message": "帮我看看 nginx 为什么不可用",
                },
                {
                    "name": "live_complex_windows_analysis",
                    "message": "分析这台 Windows 服务器 CPU 为什么飙高",
                },
            ]

            for case in cases:
                events = _chat_send_and_collect_events(
                    f"{args.base_url.rstrip('/')}/api/chat/send",
                    headers=auth_headers,
                    payload={
                        "session_id": session_id,
                        "message": case["message"],
                        "enable_streaming": False,
                    },
                    timeout_seconds=args.timeout_seconds,
                )
                text_blob = _collect_text_blob(events)
                checks.append({"name": f"{case['name']}: sse_text_preview", "status": "INFO", "details": text_blob[:1200]})
                check(checks, bool(events), f"{case['name']}: received sse events")
                check(checks, any(event.get("type") == "end" for event in events), f"{case['name']}: end event received")
                for marker in case["expected_markers"]:
                    check(checks, marker in text_blob, f"{case['name']}: marker {marker} found")

            for case in complex_cases:
                events = _chat_send_and_collect_events(
                    f"{args.base_url.rstrip('/')}/api/chat/send",
                    headers=auth_headers,
                    payload={
                        "session_id": session_id,
                        "message": case["message"],
                        "enable_streaming": False,
                    },
                    timeout_seconds=args.timeout_seconds,
                )
                text_blob = _collect_text_blob(events)
                checks.append({"name": f"{case['name']}: sse_text_preview", "status": "INFO", "details": text_blob[:1200]})
                check(checks, bool(events), f"{case['name']}: received sse events")
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
            f"{args.base_url.rstrip('/')}/api/chat/delete_session?session_id={urllib.parse.quote(session_id)}",
            method="GET",
            headers={"Authorization": auth_headers["Authorization"]},
            data=None,
            timeout_seconds=args.timeout_seconds,
        )
        check(checks, delete_payload.get("status") == "ok", "chat session deleted after live checks")
        checks.append({"name": "chat_delete_session_payload", "status": "INFO", "details": delete_payload})
    else:
        checks.append(
            {
                "name": "live_bridge_diagnosis",
                "status": "INFO",
                "details": _diagnose_live_failure(
                    reload_payload=reload_payload,
                    session_payload=session_payload,
                    reload_attempts=reload_attempts,
                    session_attempts=session_attempts,
                ),
            }
        )

    _finish(checks)


def _diagnose_live_failure(
    *,
    reload_payload: dict[str, Any],
    session_payload: dict[str, Any],
    reload_attempts: list[dict[str, Any]],
    session_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    reload_text = json.dumps(reload_payload, ensure_ascii=False)
    session_text = json.dumps(session_payload, ensure_ascii=False)
    diagnosis: dict[str, Any] = {
        "can_continue_live_bridge_test": False,
        "likely_cause": "unknown",
        "notes": [],
    }
    if "disk I/O error" in reload_text:
        diagnosis["likely_cause"] = "astrbot_sqlite_runtime_error"
        diagnosis["notes"].append("plugin reload hit SQLite disk I/O error in the running AstrBot instance")
    if session_payload.get("__http_status__") == 500:
        diagnosis["notes"].append("chat/new_session returned HTTP 500")
    if "Internal Server Error" in session_text:
        diagnosis["notes"].append("dashboard new_session endpoint is internally failing")
    if any(item.get("payload", {}).get("status") == "ok" for item in reload_attempts):
        diagnosis["notes"].append("plugin reload may be intermittent rather than permanently broken")
    if any(
        isinstance(item.get("payload", {}).get("data"), dict)
        and item["payload"]["data"].get("session_id")
        for item in session_attempts
    ):
        diagnosis["notes"].append("chat/new_session may be intermittent rather than permanently broken")
    if diagnosis["likely_cause"] == "unknown":
        diagnosis["notes"].append("inspect dashboard logs and MCP connectivity for the running instance")
    diagnosis["recommended_next_steps"] = [
        "Run verify_astrbot_ops_bridge_sync.py to confirm installed plugin matches source.",
        "Run verify_astrbot_isolated_live_ops_bridge.py to verify bridge behavior independent of the current instance state.",
        "Repair the running tmp_astrbot database/runtime before using it as authoritative live bridge evidence.",
    ]
    return diagnosis


def _check_sqlite_health(db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "path": str(db_path)}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        rows = cur.fetchall()
        cur.execute("select name from sqlite_master where type='table' and name='preferences'")
        preferences = cur.fetchall()
        conn.close()
        result["integrity_check"] = rows
        result["preferences_table"] = preferences
        result["ok"] = rows == [("ok",)] and preferences == [("preferences",)]
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


def _finish(checks: list[dict[str, Any]]) -> None:
    failed = [item for item in checks if item["status"] == "FAIL"]
    payload = {
        "total": len(checks),
        "passed": len([item for item in checks if item["status"] == "PASS"]),
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


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
            return {
                "status": "error",
                "message": "non-dict response",
                "data": parsed,
                "__http_status__": getattr(response, "status", 200),
            }
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


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
