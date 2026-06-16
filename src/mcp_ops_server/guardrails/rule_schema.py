from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mcp_ops_server.models import RiskLevel


VALID_RISK_LEVELS: set[str] = {"low", "medium", "high", "critical"}
DEFAULT_MATCH_TARGETS = ("combined_text",)


@dataclass(frozen=True)
class RuleTestCase:
    """规则自带的最小回归样例。"""

    input: str
    expect_match: bool = True
    expect_risk_level: RiskLevel | None = None
    expect_decision: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuleTestCase":
        return cls(
            input=str(payload.get("input") or ""),
            expect_match=bool(payload.get("expect_match", True)),
            expect_risk_level=_risk_or_none(payload.get("expect_risk_level")),
            expect_decision=_optional_str(payload.get("expect_decision")),
        )


@dataclass(frozen=True)
class GuardrailRuleDefinition:
    """配置文件中的单条安全规则。"""

    id: str
    category: str
    risk_level: RiskLevel
    pattern: str
    enabled: bool
    version: str
    source: str
    recommendation: str
    match_targets: tuple[str, ...] = DEFAULT_MATCH_TARGETS
    flags: tuple[str, ...] = ("ignore_case",)
    description: str | None = None
    test_cases: tuple[RuleTestCase, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GuardrailRuleDefinition":
        rule_id = str(payload.get("id") or "").strip()
        category = str(payload.get("category") or "").strip()
        risk = _risk_or_none(payload.get("risk_level"))
        pattern = str(payload.get("pattern") or "")
        if not rule_id:
            raise ValueError("guardrail rule id is required")
        if not category:
            raise ValueError(f"guardrail rule {rule_id} category is required")
        if risk is None:
            raise ValueError(f"guardrail rule {rule_id} has invalid risk_level")
        if not pattern:
            raise ValueError(f"guardrail rule {rule_id} pattern is required")
        tests = tuple(RuleTestCase.from_dict(item) for item in payload.get("test_cases") or [])
        return cls(
            id=rule_id,
            category=category,
            risk_level=risk,
            pattern=pattern,
            enabled=bool(payload.get("enabled", True)),
            version=str(payload.get("version") or "0.0.0"),
            source=str(payload.get("source") or "unspecified"),
            recommendation=str(payload.get("recommendation") or ""),
            match_targets=tuple(str(item) for item in payload.get("match_targets") or DEFAULT_MATCH_TARGETS),
            flags=tuple(str(item) for item in payload.get("flags") or ("ignore_case",)),
            description=_optional_str(payload.get("description")),
            test_cases=tests,
        )


@dataclass(frozen=True)
class CompiledGuardrailRule:
    """运行时使用的已编译规则。"""

    definition: GuardrailRuleDefinition
    pattern: re.Pattern[str]

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def category(self) -> str:
        return self.definition.category

    @property
    def risk_level(self) -> RiskLevel:
        return self.definition.risk_level

    @property
    def recommendation(self) -> str:
        return self.definition.recommendation

    @property
    def source(self) -> str:
        return self.definition.source

    @property
    def version(self) -> str:
        return self.definition.version

    @property
    def match_targets(self) -> tuple[str, ...]:
        return self.definition.match_targets


@dataclass(frozen=True)
class GuardrailRuleSet:
    """规则加载结果，包含来源和错误信息，便于诊断与答辩展示。"""

    rules: tuple[CompiledGuardrailRule, ...]
    source_path: str | None
    loaded_from_config: bool
    errors: tuple[str, ...] = field(default_factory=tuple)

    def text_rules(self) -> tuple[CompiledGuardrailRule, ...]:
        return tuple(rule for rule in self.rules if any(target in {"combined_text", "command", "user_intent", "params"} for target in rule.match_targets))

    def path_rules(self) -> tuple[CompiledGuardrailRule, ...]:
        return tuple(rule for rule in self.rules if "path" in rule.match_targets)


def compile_rule(definition: GuardrailRuleDefinition) -> CompiledGuardrailRule:
    return CompiledGuardrailRule(definition=definition, pattern=re.compile(definition.pattern, _compile_flags(definition.flags)))


def _compile_flags(flags: tuple[str, ...]) -> int:
    value = 0
    lowered = {flag.lower() for flag in flags}
    if "ignore_case" in lowered or "i" in lowered:
        value |= re.IGNORECASE
    if "dotall" in lowered or "s" in lowered:
        value |= re.DOTALL
    if "multiline" in lowered or "m" in lowered:
        value |= re.MULTILINE
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _risk_or_none(value: Any) -> RiskLevel | None:
    text = _optional_str(value)
    if text in VALID_RISK_LEVELS:
        return text  # type: ignore[return-value]
    return None
