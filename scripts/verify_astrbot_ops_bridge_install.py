from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASTRBOT_ROOT = ROOT / "tmp_astrbot"
PLUGIN_DIR = ASTRBOT_ROOT / "data" / "plugins" / "astrbot_plugin_xingxuan_mcp_filesystem"


def main() -> None:
    checks: list[dict[str, str]] = []

    check(checks, PLUGIN_DIR.exists(), "plugin directory exists")
    check(checks, (PLUGIN_DIR / "main.py").exists(), "main.py exists")
    check(checks, (PLUGIN_DIR / "intent_parser.py").exists(), "intent_parser.py exists")
    check(checks, (PLUGIN_DIR / "metadata.yaml").exists(), "metadata.yaml exists")
    check(checks, (PLUGIN_DIR / "README.md").exists(), "README.md exists")

    if str(ASTRBOT_ROOT) not in sys.path:
        sys.path.insert(0, str(ASTRBOT_ROOT))

    try:
        import data.plugins.astrbot_plugin_xingxuan_mcp_filesystem.intent_parser as parser  # type: ignore
        check(checks, hasattr(parser, "parse_intent"), "intent parser import succeeds")
    except Exception:
        check(checks, False, "intent parser import succeeds")

    try:
        import data.plugins.astrbot_plugin_xingxuan_mcp_filesystem.main as plugin_main  # type: ignore
        check(checks, hasattr(plugin_main, "TmpMcpFilesystemPlugin"), "plugin main import succeeds")
    except Exception:
        check(checks, False, "plugin main import succeeds")

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


def check(checks: list[dict[str, str]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
