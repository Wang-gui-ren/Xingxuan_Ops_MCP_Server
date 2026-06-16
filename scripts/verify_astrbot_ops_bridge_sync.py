from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SYNC_FILES = ("main.py", "intent_parser.py", "metadata.yaml", "README.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that the installed AstrBot deterministic ops bridge matches the 星璇运维MCP source plugin files.",
    )
    parser.add_argument(
        "--astrbot-plugins-dir",
        default=str(Path(__file__).resolve().parents[2] / "tmp_astrbot" / "data" / "plugins"),
        help="AstrBot data/plugins directory. Defaults to ../tmp_astrbot/data/plugins relative to tmp_mcp.",
    )
    parser.add_argument(
        "--plugin-dir-name",
        default="astrbot_plugin_xingxuan_mcp_filesystem",
        help="Installed plugin directory name inside data/plugins.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    source_dir = root / "integrations" / "astrbot_filesystem_command"
    installed_dir = Path(args.astrbot_plugins_dir).resolve() / args.plugin_dir_name

    checks: list[dict[str, object]] = []
    check(checks, source_dir.exists(), "source plugin directory exists")
    check(checks, installed_dir.exists(), "installed plugin directory exists")

    if source_dir.exists() and installed_dir.exists():
        for name in SYNC_FILES:
            source_file = source_dir / name
            installed_file = installed_dir / name
            check(checks, source_file.exists(), f"{name}: source file exists")
            check(checks, installed_file.exists(), f"{name}: installed file exists")
            if source_file.exists() and installed_file.exists():
                source_hash = _sha256(source_file)
                installed_hash = _sha256(installed_file)
                check(
                    checks,
                    source_hash == installed_hash,
                    f"{name}: installed file matches source",
                    details={
                        "source": str(source_file),
                        "installed": str(installed_file),
                        "source_sha256": source_hash,
                        "installed_sha256": installed_hash,
                    },
                )

    failed = [item for item in checks if item["status"] != "PASS"]
    payload = {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "source_dir": str(source_dir),
        "installed_dir": str(installed_dir),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(
    checks: list[dict[str, object]],
    condition: bool,
    name: str,
    *,
    details: dict[str, object] | None = None,
) -> None:
    item: dict[str, object] = {"name": name, "status": "PASS" if condition else "FAIL"}
    if details:
        item["details"] = details
    checks.append(item)


if __name__ == "__main__":
    main()
