from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp_ops_server.branding import get_prefixed_env
from mcp_ops_server.guardrails import patterns
from mcp_ops_server.guardrails.rule_schema import (
    CompiledGuardrailRule,
    GuardrailRuleDefinition,
    GuardrailRuleSet,
    compile_rule,
)


RULES_FILE_ENV = "TMP_MCP_GUARDRAIL_RULES_FILE"


def default_rules_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "guardrails" / "rules.yaml"


def clear_rule_cache() -> None:
    """测试或规则热替换后清理加载缓存。"""

    load_guardrail_rules.cache_clear()


@lru_cache(maxsize=4)
def load_guardrail_rules(path_text: str | None = None) -> GuardrailRuleSet:
    """加载配置化护栏规则，失败时回退到 Python 内置规则。"""

    path = Path(path_text or get_prefixed_env(RULES_FILE_ENV) or default_rules_path())
    if path.exists():
        try:
            payload = _load_mapping(path)
            definitions = _parse_rule_definitions(payload)
            compiled = tuple(compile_rule(definition) for definition in definitions if definition.enabled)
            return GuardrailRuleSet(rules=compiled, source_path=str(path), loaded_from_config=True)
        except Exception as exc:  # noqa: BLE001 - 配置错误不能拖垮 MCP Server
            fallback = _fallback_rules()
            return GuardrailRuleSet(
                rules=fallback,
                source_path=str(path),
                loaded_from_config=False,
                errors=(f"failed to load guardrail rules from {path}: {exc}",),
            )
    fallback = _fallback_rules()
    return GuardrailRuleSet(
        rules=fallback,
        source_path=str(path),
        loaded_from_config=False,
        errors=(f"guardrail rules file not found: {path}",),
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(text)
    except ModuleNotFoundError:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("rules file root must be a mapping")
    return payload


def _parse_rule_definitions(payload: dict[str, Any]) -> tuple[GuardrailRuleDefinition, ...]:
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("rules file must contain a list field named 'rules'")
    return tuple(GuardrailRuleDefinition.from_dict(item) for item in raw_rules if isinstance(item, dict))


def _fallback_rules() -> tuple[CompiledGuardrailRule, ...]:
    definitions: list[GuardrailRuleDefinition] = []
    for rule_id, category, pattern, risk, message, recommendation in patterns.PROMPT_INJECTION_PATTERNS + patterns.COMMAND_PATTERNS:
        definitions.append(
            GuardrailRuleDefinition(
                id=rule_id,
                category=category,
                risk_level=risk,
                pattern=pattern.pattern,
                enabled=True,
                version="fallback",
                source="mcp_ops_server.guardrails.patterns",
                recommendation=recommendation,
                match_targets=("combined_text",),
                flags=_flags_from_pattern(pattern),
                description=message,
            )
        )
    return tuple(compile_rule(definition) for definition in definitions)


def _flags_from_pattern(pattern: Any) -> tuple[str, ...]:
    flags: list[str] = []
    if pattern.flags & __import__("re").IGNORECASE:
        flags.append("ignore_case")
    if pattern.flags & __import__("re").DOTALL:
        flags.append("dotall")
    if pattern.flags & __import__("re").MULTILINE:
        flags.append("multiline")
    return tuple(flags) or ("ignore_case",)
