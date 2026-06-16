from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mcp_ops_server.models import RiskLevel


DecisionType = Literal["allow", "require_approval", "deny"]


@dataclass(frozen=True)
class GuardrailFinding:
    """一条确定性安全规则命中记录。"""

    rule_id: str
    category: str
    risk_level: RiskLevel
    message: str
    evidence: str
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "risk_level": self.risk_level,
            "message": self.message,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class ExternalGuardContext:
    """上游护栏的可选摘要，例如璇玑 Guardrail 的工具调用审查结果。"""

    provider: str = "xuanji_guardrail"
    action: str | None = None
    risk_level: RiskLevel | None = None
    score: float | None = None
    reason: str | None = None
    audit_id: str | None = None
    trace_id: str | None = None
    session_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ExternalGuardContext | None":
        if not payload:
            return None
        return cls(
            provider=str(payload.get("provider") or "xuanji_guardrail"),
            action=_optional_str(payload.get("action")),
            risk_level=_risk_or_none(payload.get("risk_level")),
            score=_optional_float(payload.get("score")),
            reason=_optional_str(payload.get("reason")),
            audit_id=_optional_str(payload.get("audit_id")),
            trace_id=_optional_str(payload.get("trace_id")),
            session_id=_optional_str(payload.get("session_id")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "action": self.action,
            "risk_level": self.risk_level,
            "score": self.score,
            "reason": self.reason,
            "audit_id": self.audit_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class OperationContext:
    """传给安全意图校验器的统一上下文。"""

    tool_name: str
    operation: str
    user_intent: str | None = None
    target: str = "local"
    platform_hint: str = "auto"
    params: dict[str, Any] = field(default_factory=dict)
    command: str | None = None
    path: str | None = None
    dry_run: bool = True
    approval_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    external_guard: ExternalGuardContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "operation": self.operation,
            "user_intent": self.user_intent,
            "target": self.target,
            "platform_hint": self.platform_hint,
            "params": self.params,
            "command": self.command,
            "path": self.path,
            "dry_run": self.dry_run,
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "external_guard": self.external_guard.to_dict() if self.external_guard else None,
        }


@dataclass(frozen=True)
class GuardrailDecision:
    """安全意图校验器的结构化决策。"""

    allowed: bool
    decision: DecisionType
    risk_level: RiskLevel
    requires_approval: bool
    summary: str
    findings: list[GuardrailFinding] = field(default_factory=list)
    safe_alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "safe_alternatives": self.safe_alternatives,
        }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_or_none(value: Any) -> RiskLevel | None:
    text = _optional_str(value)
    if text in {"low", "medium", "high", "critical"}:
        return text  # type: ignore[return-value]
    return None
