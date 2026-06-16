from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_ops_server.audit.rotation import list_audit_files
from mcp_ops_server.branding import get_prefixed_env


DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 500


@dataclass(frozen=True)
class AuditIndexStatus:
    index_file: str
    exists: bool
    indexed_files: int
    indexed_events: int
    source_files: int
    missing_files: list[str]
    last_indexed_at: str | None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_file": self.index_file,
            "exists": self.exists,
            "indexed_files": self.indexed_files,
            "indexed_events": self.indexed_events,
            "source_files": self.source_files,
            "missing_files": self.missing_files,
            "last_indexed_at": self.last_indexed_at,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class AuditSearchResult:
    events: list[dict[str, Any]]
    limit: int
    cursor: str | None
    next_cursor: str | None
    total_indexed_events: int
    index_file: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "limit": self.limit,
            "cursor": self.cursor,
            "next_cursor": self.next_cursor,
            "total_indexed_events": self.total_indexed_events,
            "index_file": self.index_file,
        }


def default_audit_index_file(audit_dir: Path) -> Path:
    configured = get_prefixed_env("TMP_MCP_AUDIT_INDEX_FILE")
    if configured:
        return Path(configured)
    return audit_dir / "index" / "audit_index.sqlite3"


def rebuild_audit_index(audit_dir: Path, *, index_file: Path | None = None) -> AuditIndexStatus:
    index_file = index_file or default_audit_index_file(audit_dir)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(index_file) as conn:
        _init_schema(conn)
        conn.execute("DELETE FROM audit_events")
        conn.execute("DELETE FROM indexed_files")
        indexed_at = datetime.now(timezone.utc).isoformat()
        for path in list_audit_files(audit_dir):
            _index_file(conn, path, indexed_at=indexed_at)
        conn.commit()
    return get_audit_index_status(audit_dir, index_file=index_file)


def ensure_audit_index(audit_dir: Path, *, index_file: Path | None = None) -> AuditIndexStatus:
    index_file = index_file or default_audit_index_file(audit_dir)
    if not index_file.exists():
        return rebuild_audit_index(audit_dir, index_file=index_file)

    with sqlite3.connect(index_file) as conn:
        _init_schema(conn)
        indexed = _indexed_file_map(conn)
        indexed_at = datetime.now(timezone.utc).isoformat()
        changed = False
        for path in list_audit_files(audit_dir):
            key = str(path)
            stat = path.stat()
            current = indexed.get(key)
            if current != (stat.st_size, stat.st_mtime):
                conn.execute("DELETE FROM audit_events WHERE audit_file = ?", (key,))
                conn.execute("DELETE FROM indexed_files WHERE audit_file = ?", (key,))
                _index_file(conn, path, indexed_at=indexed_at)
                changed = True
        if changed:
            conn.commit()
    return get_audit_index_status(audit_dir, index_file=index_file)


def get_audit_index_status(audit_dir: Path, *, index_file: Path | None = None) -> AuditIndexStatus:
    index_file = index_file or default_audit_index_file(audit_dir)
    source_files = [str(path) for path in list_audit_files(audit_dir)]
    if not index_file.exists():
        return AuditIndexStatus(
            index_file=str(index_file),
            exists=False,
            indexed_files=0,
            indexed_events=0,
            source_files=len(source_files),
            missing_files=source_files,
            last_indexed_at=None,
        )

    errors: list[str] = []
    try:
        with sqlite3.connect(index_file) as conn:
            _init_schema(conn)
            indexed_files = [row[0] for row in conn.execute("SELECT audit_file FROM indexed_files").fetchall()]
            event_count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            row = conn.execute("SELECT MAX(indexed_at) FROM indexed_files").fetchone()
            last_indexed_at = row[0] if row else None
    except sqlite3.Error as exc:
        errors.append(str(exc))
        indexed_files = []
        event_count = 0
        last_indexed_at = None

    missing = sorted(set(source_files) - set(indexed_files))
    return AuditIndexStatus(
        index_file=str(index_file),
        exists=True,
        indexed_files=len(indexed_files),
        indexed_events=event_count,
        source_files=len(source_files),
        missing_files=missing,
        last_indexed_at=last_indexed_at,
        errors=errors,
    )


def search_audit_events(
    audit_dir: Path,
    *,
    index_file: Path | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    cursor: str | None = None,
    event_type: str | None = None,
    tool_name: str | None = None,
    risk_level: str | None = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    approval_id: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
) -> AuditSearchResult:
    index_file = index_file or default_audit_index_file(audit_dir)
    ensure_audit_index(audit_dir, index_file=index_file)
    limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    offset = _decode_cursor(cursor)
    where: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("event_type", event_type),
        ("tool_name", tool_name),
        ("risk_level", risk_level),
        ("session_id", session_id),
        ("trace_id", trace_id),
        ("approval_id", approval_id),
    ):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    if time_from:
        where.append("timestamp >= ?")
        params.append(time_from)
    if time_to:
        where.append("timestamp <= ?")
        params.append(time_to)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with sqlite3.connect(index_file) as conn:
        conn.row_factory = sqlite3.Row
        total = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT event_json, audit_file, line_number, event_hash, prev_hash, chain_segment_id
            FROM audit_events
            {where_sql}
            ORDER BY timestamp DESC, audit_file DESC, line_number DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            event = json.loads(row["event_json"])
        except json.JSONDecodeError:
            event = {"event_json": row["event_json"]}
        event["audit_file"] = row["audit_file"]
        event["line_number"] = row["line_number"]
        event["event_hash"] = event.get("event_hash") or row["event_hash"]
        event["prev_hash"] = event.get("prev_hash") or row["prev_hash"]
        event["chain_segment_id"] = row["chain_segment_id"]
        events.append(event)

    next_cursor = str(offset + len(events)) if len(events) == limit else None
    return AuditSearchResult(
        events=events,
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
        total_indexed_events=total,
        index_file=str(index_file),
    )


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_file TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            event_id TEXT,
            timestamp TEXT,
            event_type TEXT,
            tool_name TEXT,
            risk_level TEXT,
            decision TEXT,
            session_id TEXT,
            trace_id TEXT,
            approval_id TEXT,
            event_hash TEXT,
            prev_hash TEXT,
            chain_segment_id TEXT,
            indexed_at TEXT NOT NULL,
            event_json TEXT NOT NULL,
            PRIMARY KEY (audit_file, line_number)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS indexed_files (
            audit_file TEXT PRIMARY KEY,
            file_size_bytes INTEGER NOT NULL,
            file_mtime REAL NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    for column in ("timestamp", "event_type", "tool_name", "risk_level", "session_id", "trace_id", "approval_id"):
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_audit_events_{column} ON audit_events({column})")


def _index_file(conn: sqlite3.Connection, path: Path, *, indexed_at: str) -> None:
    stat = path.stat()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO audit_events (
                audit_file, line_number, event_id, timestamp, event_type, tool_name, risk_level,
                decision, session_id, trace_id, approval_id, event_hash, prev_hash,
                chain_segment_id, indexed_at, event_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                line_number,
                event.get("event_id"),
                event.get("timestamp"),
                event.get("event_type"),
                event.get("tool_name"),
                event.get("risk_level"),
                event.get("decision"),
                event.get("session_id"),
                event.get("trace_id"),
                _extract_first_value(event, "approval_id"),
                event.get("event_hash"),
                event.get("prev_hash"),
                _chain_segment_id(path),
                indexed_at,
                json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )
    conn.execute(
        "INSERT OR REPLACE INTO indexed_files (audit_file, file_size_bytes, file_mtime, indexed_at) VALUES (?, ?, ?, ?)",
        (str(path), stat.st_size, stat.st_mtime, indexed_at),
    )


def _indexed_file_map(conn: sqlite3.Connection) -> dict[str, tuple[int, float]]:
    return {
        str(row[0]): (int(row[1]), float(row[2]))
        for row in conn.execute("SELECT audit_file, file_size_bytes, file_mtime FROM indexed_files").fetchall()
    }


def _extract_first_value(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        if key in value and value[key] is not None:
            return str(value[key])
        for item in value.values():
            found = _extract_first_value(item, key)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_first_value(item, key)
            if found:
                return found
    return None


def _chain_segment_id(path: Path) -> str:
    stem = path.stem
    return stem if stem.startswith("audit-") else path.name


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError:
        return 0
