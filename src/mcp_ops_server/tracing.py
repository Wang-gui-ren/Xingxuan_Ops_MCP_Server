from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp_ops_server.branding import DEFAULT_TRACE_PREFIX


@dataclass(frozen=True)
class TraceContext:
    session_id: str
    trace_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "trace_id": self.trace_id}


def ensure_trace_id(trace_id: str | None = None) -> str:
    text = _clean(trace_id)
    return text or uuid4().hex


def ensure_session_id(session_id: str | None = None) -> str:
    text = _clean(session_id)
    if text:
        return text
    date_text = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{DEFAULT_TRACE_PREFIX}-{date_text}"


def build_trace_context(session_id: str | None = None, trace_id: str | None = None) -> TraceContext:
    return TraceContext(session_id=ensure_session_id(session_id), trace_id=ensure_trace_id(trace_id))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
