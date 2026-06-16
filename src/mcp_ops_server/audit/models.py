from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp_ops_server.models import RiskLevel


@dataclass(frozen=True)
class AuditEvent:
    """JSONL 审计日志中的单条事件。"""

    event_type: str
    risk_level: RiskLevel = "low"
    tool_name: str | None = None
    decision: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    params_summary: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "risk_level": self.risk_level,
            "decision": self.decision,
            "params_summary": self.params_summary,
            "result_summary": self.result_summary,
            "error": self.error,
        }
