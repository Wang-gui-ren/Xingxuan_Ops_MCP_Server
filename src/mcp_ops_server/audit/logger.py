from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_ops_server.audit.models import AuditEvent
from mcp_ops_server.audit.rotation import current_audit_path
from mcp_ops_server.branding import get_prefixed_env


SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "token",
}

GENESIS_HASH = "sha256:GENESIS"


def default_audit_dir() -> Path:
    configured = get_prefixed_env("TMP_MCP_AUDIT_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "data" / "audit"


class AuditLogger:
    """轻量 JSONL 审计器。

    第一版保持简单可靠：同步写入本地 JSONL，失败时由调用方决定是否继续。
    """

    def __init__(self, audit_dir: Path | None = None) -> None:
        self.audit_dir = audit_dir or default_audit_dir()

    def append(self, event: AuditEvent) -> Path:
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for_today()
        payload = sanitize_payload(event.to_dict())
        payload = append_hash_chain_fields(payload, previous_hash=_read_last_event_hash(path))
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            file.write("\n")
        return path

    def read_recent(
        self,
        *,
        limit: int = 20,
        event_type: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        events: list[dict[str, Any]] = []
        for path in sorted(self.audit_dir.glob("audit-*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                continue
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_type and event.get("event_type") != event_type:
                    continue
                if tool_name and event.get("tool_name") != tool_name:
                    continue
                if risk_level and event.get("risk_level") != risk_level:
                    continue
                if session_id and event.get("session_id") != session_id:
                    continue
                if trace_id and event.get("trace_id") != trace_id:
                    continue
                events.append(event)
                if len(events) >= limit:
                    return events
        return events

    def _path_for_today(self) -> Path:
        date_text = datetime.now().strftime("%Y%m%d")
        return current_audit_path(self.audit_dir, date_key=date_text)


def sanitize_payload(value: Any, *, max_string_length: int = 500) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if callable(value):
        name = getattr(value, "__name__", value.__class__.__name__)
        return f"<callable:{name}>"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(key)
            if _is_sensitive_key(safe_key):
                sanitized[safe_key] = "***REDACTED***"
            else:
                sanitized[safe_key] = sanitize_payload(item, max_string_length=max_string_length)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item, max_string_length=max_string_length) for item in value[:100]]
    if isinstance(value, tuple):
        return [sanitize_payload(item, max_string_length=max_string_length) for item in value[:100]]
    if isinstance(value, (set, frozenset)):
        return [sanitize_payload(item, max_string_length=max_string_length) for item in list(value)[:100]]
    if isinstance(value, str):
        compact = value if len(value) <= max_string_length else value[:max_string_length] + "...<truncated>"
        return _redact_inline_secret(compact)
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        text = str(value)
        compact = text if len(text) <= max_string_length else text[:max_string_length] + "...<truncated>"
        return _redact_inline_secret(compact)


def append_hash_chain_fields(payload: dict[str, Any], *, previous_hash: str) -> dict[str, Any]:
    """为审计事件追加哈希链字段。

    哈希基于最终落盘 payload 的规范化 JSON，因此要在脱敏之后计算。
    """

    chained = dict(payload)
    chained["prev_hash"] = previous_hash
    chained["event_hash"] = compute_event_hash(chained, previous_hash=previous_hash)
    return chained


def compute_event_hash(payload: dict[str, Any], *, previous_hash: str | None = None) -> str:
    canonical_payload = {key: value for key, value in payload.items() if key not in {"prev_hash", "event_hash"}}
    prev = previous_hash if previous_hash is not None else str(payload.get("prev_hash") or GENESIS_HASH)
    canonical = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{prev}\n{canonical}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": result.get("ok"),
        "risk_level": result.get("risk_level"),
        "summary": result.get("summary"),
        "data_status": _extract_data_status(result.get("data")),
        "next_actions_count": len(result.get("next_actions") or []),
    }


def _extract_data_status(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    if "status" in data:
        return data.get("status")
    if "action" in data:
        return data.get("action")
    return None


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in SENSITIVE_KEYS)


def _redact_inline_secret(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("password=", "token=", "secret=", "api_key=")):
        return "***REDACTED_INLINE_SECRET***"
    return text


def _read_last_event_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS_HASH
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            position = file.tell()
            buffer = bytearray()
            while position > 0:
                position -= 1
                file.seek(position)
                char = file.read(1)
                if char == b"\n" and buffer:
                    break
                if char != b"\n":
                    buffer.extend(char)
        if not buffer:
            return GENESIS_HASH
        line = bytes(reversed(buffer)).decode("utf-8")
        event = json.loads(line)
        return str(event.get("event_hash") or GENESIS_HASH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return GENESIS_HASH
