from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PARSER_DIR = ROOT / "integrations" / "astrbot_filesystem_command"

for candidate in (SRC, PARSER_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from intent_parser import parse_intent  # type: ignore  # noqa: E402
from mcp_ops_server.audit import AuditLogger  # noqa: E402
from mcp_ops_server.tool_groups import register_basic_tools  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_remote_profile_") as tmp:
        root = Path(tmp)
        audit_logger = AuditLogger(root / "audit")
        mcp = FakeMCP()
        del audit_logger  # reserved for parity with other verify scripts
        register_basic_tools(mcp)

        cases = [
            {
                "name": "remote_linux_profile_intent",
                "message": "查看远程 linux 服务器 192.168.1.20 用户 ops 端口 22 的主机画像",
                "expected_args": {"target": "192.168.1.20", "platform_hint": "linux", "username": "ops", "port": 22},
            },
            {
                "name": "remote_windows_profile_intent",
                "message": "查看远程 windows 服务器 win-server-01 的主机画像",
                "expected_args": {"target": "win-server-01", "platform_hint": "windows"},
            },
        ]

        for case in cases:
            intent = parse_intent(case["message"])
            check(checks, intent is not None, f"{case['name']}: intent parsed")
            if intent is None:
                continue
            check(checks, intent.tool_name == "get_host_profile_tool", f"{case['name']}: tool selected")
            for key, value in case["expected_args"].items():
                check(checks, intent.arguments.get(key) == value, f"{case['name']}: argument {key} matched")

            result = mcp.tools["get_host_profile_tool"](**intent.arguments)
            check(checks, result.get("ok") is False, f"{case['name']}: current remote profile result is non-success")
            check(checks, result.get("risk_level") == "medium", f"{case['name']}: risk level is medium on remote failure")
            data = result.get("data", {})
            collection = data.get("collection", {}) if isinstance(data, dict) else {}
            check(checks, collection.get("success") is False, f"{case['name']}: collection.success false")
            check(checks, collection.get("mode") == "unavailable", f"{case['name']}: collection.mode unavailable")
            attempts = collection.get("attempts") if isinstance(collection, dict) else []
            expected_attempt = "ssh/linux" if case["expected_args"]["platform_hint"] == "linux" else "winrm/windows"
            check(checks, expected_attempt in attempts, f"{case['name']}: expected attempt recorded")
            check(
                checks,
                "Unable to collect remote host profile" in str(collection.get("error", "")),
                f"{case['name']}: generic remote failure error returned",
            )

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


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
