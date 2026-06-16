from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare offline SQLite health with live AstrBot dashboard DB behavior to pinpoint runtime-layer failures.",
    )
    parser.add_argument(
        "--astrbot-root",
        default=str(Path(__file__).resolve().parents[2] / "tmp_astrbot"),
        help="AstrBot project root containing data/data_v4.db.",
    )
    parser.add_argument(
        "--python-exe",
        default="D:\\miniconda\\envs\\astrbot\\python.exe",
        help="Python executable for AstrBot environment.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.astrbot_root).resolve()
    checks: list[dict[str, Any]] = []

    db_path = root / "data" / "data_v4.db"
    check(checks, db_path.exists(), "data_v4.db exists")
    if not db_path.exists():
        _finish(checks)
        return

    offline = _offline_sqlite_probe(db_path)
    checks.append({"name": "offline_sqlite_probe", "status": "INFO", "details": offline})
    check(checks, offline.get("integrity_ok") is True, "offline sqlite integrity ok")
    check(checks, offline.get("preferences_query_ok") is True, "offline preferences query ok")
    check(checks, offline.get("create_delete_session_ok") is True, "offline create/delete session ok")

    live = asyncio.run(_astrbot_async_probe(root, python_exe=args.python_exe))
    checks.append({"name": "astrbot_async_probe", "status": "INFO", "details": live})
    check(checks, live.get("initialize_ok") is True, "AstrBot SQLiteDatabase initialize ok")
    check(checks, live.get("global_get_ok") is True, "AstrBot SharedPreferences global_get ok")
    check(checks, live.get("create_delete_session_ok") is True, "AstrBot SQLiteDatabase create/delete session ok")

    likely_runtime_only = (
        offline.get("integrity_ok") is True
        and offline.get("preferences_query_ok") is True
        and offline.get("create_delete_session_ok") is True
        and live.get("initialize_ok") is True
        and live.get("global_get_ok") is True
        and live.get("create_delete_session_ok") is True
    )
    check(checks, likely_runtime_only, "offline and standalone AstrBot DB probes both healthy")
    checks.append(
        {
            "name": "runtime_health_conclusion",
            "status": "INFO",
            "details": {
                "db_file_is_healthy": likely_runtime_only,
                "interpretation": (
                    "If verify_astrbot_live_ops_bridge.py still reports /api/plugin/reload disk I/O error or /api/chat/new_session 500 while this script passes, the fault is likely in the running AstrBot process state rather than the SQLite file itself."
                ),
            },
        }
    )

    _finish(checks)


def _offline_sqlite_probe(db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(db_path),
        "integrity_ok": False,
        "preferences_query_ok": False,
        "create_delete_session_ok": False,
    }
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        integrity_rows = cur.fetchall()
        result["integrity_check"] = integrity_rows
        result["integrity_ok"] = integrity_rows == [("ok",)]

        cur.execute("select count(*) from preferences")
        result["preferences_count"] = cur.fetchall()
        cur.execute("select id, scope, scope_id, key from preferences where scope='global' and scope_id='global'")
        result["preferences_sample"] = cur.fetchmany(5)
        result["preferences_query_ok"] = True

        cur.execute(
            "insert into platform_sessions (session_id, platform_id, creator, display_name, is_group, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("runtime-db-health-offline", "webchat", "runtime-db-health", "runtime-db-health", 0),
        )
        row_id = cur.lastrowid
        conn.commit()
        cur.execute("delete from platform_sessions where inner_id = ?", (row_id,))
        conn.commit()
        result["create_delete_session_ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    finally:
        conn.close()
    return result


async def _astrbot_async_probe(root: Path, *, python_exe: str) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import os

    os.environ["ASTRBOT_ROOT"] = str(root)

    from astrbot.core.db.sqlite import SQLiteDatabase  # type: ignore
    from astrbot.core.utils.shared_preferences import SharedPreferences  # type: ignore

    db = SQLiteDatabase(str(root / "data" / "data_v4.db"))
    result: dict[str, Any] = {
        "initialize_ok": False,
        "global_get_ok": False,
        "create_delete_session_ok": False,
        "python_exe": python_exe,
    }

    try:
        await db.initialize()
        result["initialize_ok"] = True

        sp = SharedPreferences(db)
        global_val = await sp.global_get("inactivated_plugins", [])
        result["global_get_result_type"] = type(global_val).__name__
        result["global_get_result"] = global_val
        result["global_get_ok"] = True

        session = await db.create_platform_session(
            creator="runtime-db-health",
            platform_id="webchat",
            display_name="runtime-db-health",
            is_group=0,
        )
        result["created_session_id"] = getattr(session, "session_id", None)
        await db.delete_platform_session(session.session_id)
        result["create_delete_session_ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    finally:
        try:
            await db.engine.dispose()
        except Exception:
            pass
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


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
