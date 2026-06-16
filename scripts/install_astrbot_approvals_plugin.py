from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the 星璇运维MCP /approvals AstrBot plugin into an AstrBot data/plugins directory.",
    )
    parser.add_argument(
        "--astrbot-plugins-dir",
        required=True,
        help="Target AstrBot plugins directory, for example G:\\完整mcp\\tmp_astrbot\\data\\plugins",
    )
    parser.add_argument(
        "--plugin-dir-name",
        default="astrbot_plugin_xingxuan_mcp_approvals",
        help="Destination plugin directory name inside data/plugins",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination plugin directory if it already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = Path(__file__).resolve().parents[1] / "integrations" / "astrbot_approvals_command"
    target_root = Path(args.astrbot_plugins_dir).resolve()
    target_dir = target_root / args.plugin_dir_name

    if not source_dir.exists():
        raise SystemExit(f"Source plugin directory does not exist: {source_dir}")

    target_root.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        if not args.force:
            raise SystemExit(
                f"Target plugin directory already exists: {target_dir}\n"
                "Use --force to overwrite it."
            )
        shutil.rmtree(target_dir)

    shutil.copytree(
        source_dir,
        target_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    print(f"Installed 星璇运维MCP approvals plugin to: {target_dir}")
    print("Reload plugins in AstrBot WebUI, then test /approvals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
