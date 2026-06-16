from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PARSER_DIR = ROOT / "integrations" / "astrbot_filesystem_command"
if str(PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(PARSER_DIR))

from intent_parser import parse_intent  # type: ignore  # noqa: E402


def main() -> None:
    checks: list[dict[str, str]] = []

    cases = [
        (
            "create_file_windows",
            "在 G:\\完整mcp 中建立一个文件 111.json",
            "request_create_file",
            {
                "path": "G:\\完整mcp\\111.json",
                "platform_hint": "windows",
                "dry_run": True,
                "overwrite_if_exists": False,
                "create_parents": False,
                "content": "",
            },
        ),
        (
            "create_directory_windows",
            "在 C:\\tmp 这个文件夹新建一个空文件夹：名字叫“test1”",
            "request_create_directory",
            {"path": "C:\\tmp\\test1", "platform_hint": "windows", "dry_run": True},
        ),
        (
            "create_directory_linux",
            "在 /tmp 这个文件夹新建一个空目录：名字叫 test1",
            "request_create_directory",
            {"path": "/tmp/test1", "platform_hint": "linux", "dry_run": True},
        ),
        (
            "restart_service_windows",
            "重启 Spooler 服务",
            "request_restart_service",
            {"service": "Spooler", "platform_hint": "windows", "dry_run": True},
        ),
        (
            "restart_service_linux",
            "重启 nginx 服务",
            "request_restart_service",
            {"service": "nginx", "platform_hint": "linux", "dry_run": True},
        ),
        (
            "network_plan_windows",
            "开放 tcp 8080 端口",
            "request_network_policy_change",
            {"action": "allow", "protocol": "tcp", "port": 8080, "dry_run": True},
        ),
        (
            "network_plan_block",
            "阻断 3389 端口",
            "request_network_policy_change",
            {"action": "deny", "port": 3389, "dry_run": True},
        ),
        (
            "log_archive_linux",
            "归档 /var/log/nginx/access.log",
            "request_log_cleanup",
            {"path": "/var/log/nginx/access.log", "mode": "archive", "platform_hint": "linux", "dry_run": True},
        ),
        (
            "log_quarantine_windows",
            "隔离 C:\\logs\\app.log",
            "request_log_cleanup",
            {"path": "C:\\logs\\app.log", "mode": "quarantine", "platform_hint": "windows", "dry_run": True},
        ),
        (
            "local_host_profile",
            "查询电脑配置",
            "get_host_profile_tool",
            {"target": "local", "platform_hint": "auto", "timeout_seconds": 8},
        ),
        (
            "remote_linux_profile",
            "查看远程 linux 服务器 192.168.1.20 用户 ops 端口 22 的主机画像",
            "get_host_profile_tool",
            {"target": "192.168.1.20", "platform_hint": "linux", "username": "ops", "port": 22, "timeout_seconds": 8},
        ),
        (
            "remote_windows_profile",
            "查看远程 windows 服务器 win-server-01 的主机画像",
            "get_host_profile_tool",
            {"target": "win-server-01", "platform_hint": "windows", "timeout_seconds": 8},
        ),
        (
            "remote_linux_restart_service",
            "重启远程 linux 服务器 192.168.1.20 上的 nginx 服务 用户 ops 端口 22",
            "request_restart_service",
            {"service": "nginx", "target": "192.168.1.20", "platform_hint": "linux", "remote_username": "ops", "remote_port": 22, "dry_run": True},
        ),
        (
            "remote_windows_restart_service",
            "重启远程 windows 服务器 win-server-01 上的 Spooler 服务 账号 admin 端口 5985",
            "request_restart_service",
            {"service": "Spooler", "target": "win-server-01", "platform_hint": "windows", "remote_username": "admin", "remote_port": 5985, "dry_run": True},
        ),
        (
            "non_bridge_complex_question",
            "帮我看看 nginx 为什么不可用",
            None,
            {},
        ),
    ]

    for name, text, expected_tool, expected_args in cases:
        intent = parse_intent(text)
        if expected_tool is None:
            ok = intent is None
            checks.append({"name": name, "status": "PASS" if ok else "FAIL"})
            continue
        ok = intent is not None and intent.tool_name == expected_tool
        if ok:
            for key, value in expected_args.items():
                if intent.arguments.get(key) != value:
                    ok = False
                    break
        item = {"name": name, "status": "PASS" if ok else "FAIL"}
        if not ok:
            item["expected"] = {"tool": expected_tool, "arguments": expected_args}
            item["actual"] = {
                "tool": getattr(intent, "tool_name", None),
                "arguments": getattr(intent, "arguments", None),
            }
        checks.append(item)

    failed = [item for item in checks if item["status"] != "PASS"]
    payload = {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
