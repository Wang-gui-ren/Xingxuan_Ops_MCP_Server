from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_ops_server.branding import (
    LEGACY_UI_STYLE_NAME,
    UI_STYLE_NAME,
    get_compat_env,
    get_compat_env_source,
)


WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV = "XINGXUAN_MCP_WEB_GATEWAY_CONFIG_FILE"
LEGACY_WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV = "TMP_MCP_WEB_GATEWAY_CONFIG_FILE"
GATEWAY_DEFAULT_PAGE_ENV = "XINGXUAN_MCP_GATEWAY_DEFAULT_PAGE"
LEGACY_GATEWAY_DEFAULT_PAGE_ENV = "TMP_MCP_GATEWAY_DEFAULT_PAGE"
GATEWAY_UI_STYLE_ENV = "XINGXUAN_MCP_GATEWAY_UI_STYLE"
LEGACY_GATEWAY_UI_STYLE_ENV = "TMP_MCP_GATEWAY_UI_STYLE"
GATEWAY_DENSITY_ENV = "XINGXUAN_MCP_GATEWAY_DENSITY"
LEGACY_GATEWAY_DENSITY_ENV = "TMP_MCP_GATEWAY_DENSITY"
GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV = "XINGXUAN_MCP_GATEWAY_ENABLE_APPROVAL_CONSOLE"
LEGACY_GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV = "TMP_MCP_GATEWAY_ENABLE_APPROVAL_CONSOLE"
GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV = "XINGXUAN_MCP_GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE"
LEGACY_GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV = "TMP_MCP_GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE"
GATEWAY_ENABLE_READ_APIS_ENV = "XINGXUAN_MCP_GATEWAY_ENABLE_READ_APIS"
LEGACY_GATEWAY_ENABLE_READ_APIS_ENV = "TMP_MCP_GATEWAY_ENABLE_READ_APIS"
GATEWAY_ENABLE_MUTATION_APIS_ENV = "XINGXUAN_MCP_GATEWAY_ENABLE_MUTATION_APIS"
LEGACY_GATEWAY_ENABLE_MUTATION_APIS_ENV = "TMP_MCP_GATEWAY_ENABLE_MUTATION_APIS"
GATEWAY_SHOW_SETTINGS_ENV = "XINGXUAN_MCP_GATEWAY_SHOW_SETTINGS"
LEGACY_GATEWAY_SHOW_SETTINGS_ENV = "TMP_MCP_GATEWAY_SHOW_SETTINGS"
GATEWAY_SHOW_API_INDEX_ENV = "XINGXUAN_MCP_GATEWAY_SHOW_API_INDEX"
LEGACY_GATEWAY_SHOW_API_INDEX_ENV = "TMP_MCP_GATEWAY_SHOW_API_INDEX"

WEB_GATEWAY_OPTIONS_SCHEMA_VERSION = "web-gateway-options-v1"

_ALLOWED_TOP_LEVEL_KEYS = {"schema_version", "ui", "features", "security"}
_ALLOWED_SECTION_KEYS = {
    "ui": {"default_page", "style", "density"},
    "features": {
        "enable_approval_console",
        "enable_config_admin_console",
        "enable_read_apis",
        "enable_mutation_apis",
        "show_gateway_settings",
        "show_api_index",
    },
    "security": {"require_admin_token_for_mutation"},
}
_ALLOWED_DEFAULT_PAGES = {"approvals", "config-admin"}
_ALLOWED_UI_STYLES = {"semi_design", "astrbot_like", UI_STYLE_NAME, LEGACY_UI_STYLE_NAME}
_ALLOWED_DENSITIES = {"compact", "comfortable"}


@dataclass(frozen=True)
class EffectiveWebGatewayOptions:
    schema_version: str
    default_page: str
    ui_style: str
    density: str
    enable_approval_console: bool
    enable_config_admin_console: bool
    enable_read_apis: bool
    enable_mutation_apis: bool
    show_gateway_settings: bool
    show_api_index: bool
    require_admin_token_for_mutation: bool
    primary_config_path: str | None = None
    source_map: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def effective_config(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "default_page": self.default_page,
            "ui_style": self.ui_style,
            "density": self.density,
            "enable_approval_console": self.enable_approval_console,
            "enable_config_admin_console": self.enable_config_admin_console,
            "enable_read_apis": self.enable_read_apis,
            "enable_mutation_apis": self.enable_mutation_apis,
            "show_gateway_settings": self.show_gateway_settings,
            "show_api_index": self.show_api_index,
            "require_admin_token_for_mutation": self.require_admin_token_for_mutation,
        }

    def ui(self) -> dict[str, Any]:
        return {
            "default_page": self.default_page,
            "style": self.ui_style,
            "density": self.density,
        }

    def features(self) -> dict[str, Any]:
        return {
            "enable_approval_console": self.enable_approval_console,
            "enable_config_admin_console": self.enable_config_admin_console,
            "enable_read_apis": self.enable_read_apis,
            "enable_mutation_apis": self.enable_mutation_apis,
            "show_gateway_settings": self.show_gateway_settings,
            "show_api_index": self.show_api_index,
        }

    def security(self) -> dict[str, Any]:
        return {
            "require_admin_token_for_mutation": self.require_admin_token_for_mutation,
        }

    def config_paths(self) -> dict[str, Any]:
        return {"primary_config_path": self.primary_config_path}

    def to_public_dict(self, *, include_sources: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "effective_config": self.effective_config(),
            "ui": self.ui(),
            "features": self.features(),
            "security": self.security(),
            "config_paths": self.config_paths(),
            "warnings": list(self.warnings),
            "restart_required": False,
        }
        if include_sources:
            payload["source_map"] = dict(self.source_map)
        return payload


@dataclass(frozen=True)
class WebGatewayOptionsValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposed_options: dict[str, Any] = field(default_factory=dict)
    normalized_patch: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "proposed_options": dict(self.proposed_options),
            "normalized_patch": dict(self.normalized_patch),
        }


def default_web_gateway_options_config_path() -> Path:
    configured = get_compat_env(WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV, LEGACY_WEB_GATEWAY_OPTIONS_CONFIG_FILE_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "config" / "web_gateway.json"


def default_web_gateway_options_payload() -> dict[str, Any]:
    return {
        "schema_version": WEB_GATEWAY_OPTIONS_SCHEMA_VERSION,
        "ui": {
            "default_page": "approvals",
            "style": UI_STYLE_NAME,
            "density": "compact",
        },
        "features": {
            "enable_approval_console": True,
            "enable_config_admin_console": True,
            "enable_read_apis": True,
            "enable_mutation_apis": True,
            "show_gateway_settings": True,
            "show_api_index": True,
        },
        "security": {
            "require_admin_token_for_mutation": True,
        },
    }


def load_web_gateway_options(
    *,
    config_file: str | Path | None = None,
    primary_payload_override: dict[str, Any] | None = None,
) -> EffectiveWebGatewayOptions:
    primary_path = Path(config_file) if config_file is not None else default_web_gateway_options_config_path()
    primary_payload = (
        _deep_merge(default_web_gateway_options_payload(), primary_payload_override)
        if primary_payload_override is not None
        else _deep_merge(default_web_gateway_options_payload(), _read_json_object(primary_path))
    )
    warnings: list[str] = []
    source_map = _source_map_from_payload(primary_payload, "file")

    if not primary_path.exists() and primary_payload_override is None:
        warnings.append(f"primary config file not found: {primary_path}")

    ui = _section(primary_payload, "ui")
    features = _section(primary_payload, "features")
    security = _section(primary_payload, "security")

    default_page = _safe_choice(ui.get("default_page"), _ALLOWED_DEFAULT_PAGES, "approvals", warnings, "ui.default_page")
    ui_style = _safe_choice(ui.get("style"), _ALLOWED_UI_STYLES, UI_STYLE_NAME, warnings, "ui.style")
    density = _safe_choice(ui.get("density"), _ALLOWED_DENSITIES, "compact", warnings, "ui.density")

    enable_approval_console = _as_bool(features.get("enable_approval_console"), True)
    enable_config_admin_console = _as_bool(features.get("enable_config_admin_console"), True)
    enable_read_apis = _as_bool(features.get("enable_read_apis"), True)
    enable_mutation_apis = _as_bool(features.get("enable_mutation_apis"), True)
    show_gateway_settings = _as_bool(features.get("show_gateway_settings"), True)
    show_api_index = _as_bool(features.get("show_api_index"), True)
    require_admin_token = _as_bool(security.get("require_admin_token_for_mutation"), True)

    env_value = get_compat_env(GATEWAY_DEFAULT_PAGE_ENV, LEGACY_GATEWAY_DEFAULT_PAGE_ENV)
    if env_value is not None:
        default_page = _safe_choice(env_value, _ALLOWED_DEFAULT_PAGES, default_page, warnings, GATEWAY_DEFAULT_PAGE_ENV)
        source_map["ui.default_page"] = f"env:{get_compat_env_source(GATEWAY_DEFAULT_PAGE_ENV, LEGACY_GATEWAY_DEFAULT_PAGE_ENV) or GATEWAY_DEFAULT_PAGE_ENV}"
    env_value = get_compat_env(GATEWAY_UI_STYLE_ENV, LEGACY_GATEWAY_UI_STYLE_ENV)
    if env_value is not None:
        ui_style = _safe_choice(env_value, _ALLOWED_UI_STYLES, ui_style, warnings, GATEWAY_UI_STYLE_ENV)
        source_map["ui.style"] = f"env:{get_compat_env_source(GATEWAY_UI_STYLE_ENV, LEGACY_GATEWAY_UI_STYLE_ENV) or GATEWAY_UI_STYLE_ENV}"
    env_value = get_compat_env(GATEWAY_DENSITY_ENV, LEGACY_GATEWAY_DENSITY_ENV)
    if env_value is not None:
        density = _safe_choice(env_value, _ALLOWED_DENSITIES, density, warnings, GATEWAY_DENSITY_ENV)
        source_map["ui.density"] = f"env:{get_compat_env_source(GATEWAY_DENSITY_ENV, LEGACY_GATEWAY_DENSITY_ENV) or GATEWAY_DENSITY_ENV}"

    env_bool = _env_bool(GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV, LEGACY_GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV)
    if env_bool is not None:
        enable_approval_console = env_bool
        source_map["features.enable_approval_console"] = f"env:{get_compat_env_source(GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV, LEGACY_GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV) or GATEWAY_ENABLE_APPROVAL_CONSOLE_ENV}"
    env_bool = _env_bool(GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV, LEGACY_GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV)
    if env_bool is not None:
        enable_config_admin_console = env_bool
        source_map["features.enable_config_admin_console"] = f"env:{get_compat_env_source(GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV, LEGACY_GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV) or GATEWAY_ENABLE_CONFIG_ADMIN_CONSOLE_ENV}"
    env_bool = _env_bool(GATEWAY_ENABLE_READ_APIS_ENV, LEGACY_GATEWAY_ENABLE_READ_APIS_ENV)
    if env_bool is not None:
        enable_read_apis = env_bool
        source_map["features.enable_read_apis"] = f"env:{get_compat_env_source(GATEWAY_ENABLE_READ_APIS_ENV, LEGACY_GATEWAY_ENABLE_READ_APIS_ENV) or GATEWAY_ENABLE_READ_APIS_ENV}"
    env_bool = _env_bool(GATEWAY_ENABLE_MUTATION_APIS_ENV, LEGACY_GATEWAY_ENABLE_MUTATION_APIS_ENV)
    if env_bool is not None:
        enable_mutation_apis = env_bool
        source_map["features.enable_mutation_apis"] = f"env:{get_compat_env_source(GATEWAY_ENABLE_MUTATION_APIS_ENV, LEGACY_GATEWAY_ENABLE_MUTATION_APIS_ENV) or GATEWAY_ENABLE_MUTATION_APIS_ENV}"
    env_bool = _env_bool(GATEWAY_SHOW_SETTINGS_ENV, LEGACY_GATEWAY_SHOW_SETTINGS_ENV)
    if env_bool is not None:
        show_gateway_settings = env_bool
        source_map["features.show_gateway_settings"] = f"env:{get_compat_env_source(GATEWAY_SHOW_SETTINGS_ENV, LEGACY_GATEWAY_SHOW_SETTINGS_ENV) or GATEWAY_SHOW_SETTINGS_ENV}"
    env_bool = _env_bool(GATEWAY_SHOW_API_INDEX_ENV, LEGACY_GATEWAY_SHOW_API_INDEX_ENV)
    if env_bool is not None:
        show_api_index = env_bool
        source_map["features.show_api_index"] = f"env:{get_compat_env_source(GATEWAY_SHOW_API_INDEX_ENV, LEGACY_GATEWAY_SHOW_API_INDEX_ENV) or GATEWAY_SHOW_API_INDEX_ENV}"

    if enable_mutation_apis and not require_admin_token:
        require_admin_token = True
        warnings.append("mutation APIs require the gateway admin token guard; unsafe config was forced to true")
    if not enable_approval_console and not enable_config_admin_console:
        warnings.append("both page consoles are disabled; only health/settings routes can remain useful")

    return EffectiveWebGatewayOptions(
        schema_version=str(primary_payload.get("schema_version") or WEB_GATEWAY_OPTIONS_SCHEMA_VERSION),
        default_page=default_page,
        ui_style=ui_style,
        density=density,
        enable_approval_console=enable_approval_console,
        enable_config_admin_console=enable_config_admin_console,
        enable_read_apis=enable_read_apis,
        enable_mutation_apis=enable_mutation_apis,
        show_gateway_settings=show_gateway_settings,
        show_api_index=show_api_index,
        require_admin_token_for_mutation=require_admin_token,
        primary_config_path=str(primary_path),
        source_map=source_map,
        warnings=tuple(warnings),
    )


def validate_web_gateway_options_patch(
    config_patch: dict[str, Any] | None,
    *,
    config_file: str | Path | None = None,
) -> WebGatewayOptionsValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if config_patch is None:
        config_patch = {}
    if not isinstance(config_patch, dict):
        return WebGatewayOptionsValidation(
            ok=False,
            errors=["config_patch must be a json object"],
            proposed_options=load_web_gateway_options(config_file=config_file).to_public_dict(include_sources=True),
        )

    normalized_patch = _normalize_patch(config_patch, errors, warnings)
    current_path = Path(config_file) if config_file is not None else default_web_gateway_options_config_path()
    current_payload = _deep_merge(default_web_gateway_options_payload(), _read_json_object(current_path))
    proposed_payload = _deep_merge(current_payload, normalized_patch)
    proposed = load_web_gateway_options(config_file=current_path, primary_payload_override=proposed_payload)
    proposed_config = proposed.to_public_dict(include_sources=True)

    features = proposed.features()
    if not features["enable_approval_console"] and not features["enable_config_admin_console"]:
        errors.append("at least one console page must stay enabled")
    if proposed.default_page == "approvals" and not features["enable_approval_console"]:
        errors.append("ui.default_page=approvals requires features.enable_approval_console=true")
    if proposed.default_page == "config-admin" and not features["enable_config_admin_console"]:
        errors.append("ui.default_page=config-admin requires features.enable_config_admin_console=true")
    if features["enable_mutation_apis"] and not proposed.security()["require_admin_token_for_mutation"]:
        errors.append("mutation APIs must require the gateway admin token")
    if not features["enable_read_apis"]:
        warnings.append("read JSON APIs will be blocked, while server-rendered pages can still load")
    if not features["enable_mutation_apis"]:
        warnings.append("approval/config write buttons will be disabled at the gateway boundary")

    return WebGatewayOptionsValidation(
        ok=not errors,
        errors=errors,
        warnings=warnings + list(proposed.warnings),
        proposed_options=proposed_config,
        normalized_patch=normalized_patch,
    )


def update_web_gateway_options(
    config_patch: dict[str, Any] | None,
    *,
    updated_by: str = "gateway-admin",
    change_reason: str | None = None,
    config_file: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_web_gateway_options_patch(config_patch, config_file=config_file)
    current_path = Path(config_file) if config_file is not None else default_web_gateway_options_config_path()
    before = load_web_gateway_options(config_file=current_path)
    if not validation.ok:
        return {
            "ok": False,
            "schema_version": WEB_GATEWAY_OPTIONS_SCHEMA_VERSION,
            "summary": "Gateway options validation failed.",
            "data": {"validation": validation.to_dict()},
            "next_actions": ["Fix the gateway options patch and submit it again."],
        }

    current_payload = _deep_merge(default_web_gateway_options_payload(), _read_json_object(current_path))
    merged_payload = _deep_merge(current_payload, validation.normalized_patch)
    _atomic_write_json(current_path, _config_payload_for_write(merged_payload))
    after = load_web_gateway_options(config_file=current_path)
    return {
        "ok": True,
        "schema_version": WEB_GATEWAY_OPTIONS_SCHEMA_VERSION,
        "summary": "Gateway options updated.",
        "data": {
            "options": after.to_public_dict(include_sources=True),
            "validation": validation.to_dict(),
            "diff_summary": _diff_summary(before.effective_config(), after.effective_config()),
            "updated_by": updated_by,
            "change_reason": change_reason,
        },
        "next_actions": ["Reload the hosted B/S gateway page to apply the new console options."],
    }


def _normalize_patch(config_patch: dict[str, Any], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    unknown_top = sorted(set(config_patch) - _ALLOWED_TOP_LEVEL_KEYS)
    if unknown_top:
        errors.append(f"unknown top-level key(s): {', '.join(unknown_top)}")
    schema_version = config_patch.get("schema_version")
    if schema_version is not None:
        if schema_version != WEB_GATEWAY_OPTIONS_SCHEMA_VERSION:
            errors.append(f"schema_version must be {WEB_GATEWAY_OPTIONS_SCHEMA_VERSION}")
        else:
            normalized["schema_version"] = schema_version
    for section, allowed_keys in _ALLOWED_SECTION_KEYS.items():
        raw_section = config_patch.get(section)
        if raw_section is None:
            continue
        if not isinstance(raw_section, dict):
            errors.append(f"{section} must be a json object")
            continue
        unknown = sorted(set(raw_section) - allowed_keys)
        if unknown:
            errors.append(f"unknown {section} key(s): {', '.join(unknown)}")
        normalized_section: dict[str, Any] = {}
        for key, value in raw_section.items():
            if key not in allowed_keys:
                continue
            path = f"{section}.{key}"
            if path == "ui.default_page":
                _normalize_choice(value, _ALLOWED_DEFAULT_PAGES, path, normalized_section, key, errors)
            elif path == "ui.style":
                _normalize_choice(value, _ALLOWED_UI_STYLES, path, normalized_section, key, errors)
            elif path == "ui.density":
                _normalize_choice(value, _ALLOWED_DENSITIES, path, normalized_section, key, errors)
            else:
                normalized_section[key] = _normalize_bool(value, path, errors)
        if normalized_section:
            normalized[section] = normalized_section
    if not normalized and not errors:
        warnings.append("empty patch; proposed options equal current options")
    return normalized


def _normalize_choice(
    value: Any,
    allowed: set[str],
    path: str,
    target: dict[str, Any],
    key: str,
    errors: list[str],
) -> None:
    text = str(value or "").strip()
    if text not in allowed:
        errors.append(f"{path} must be one of: {', '.join(sorted(allowed))}")
        return
    target[key] = text


def _normalize_bool(value: Any, path: str, errors: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    errors.append(f"{path} must be boolean")
    return False


def _config_payload_for_write(payload: dict[str, Any]) -> dict[str, Any]:
    ui = _section(payload, "ui")
    features = _section(payload, "features")
    security = _section(payload, "security")
    return {
        "schema_version": WEB_GATEWAY_OPTIONS_SCHEMA_VERSION,
        "ui": {
            "default_page": ui.get("default_page", "approvals"),
            "style": ui.get("style", UI_STYLE_NAME),
            "density": ui.get("density", "compact"),
        },
        "features": {
            "enable_approval_console": _as_bool(features.get("enable_approval_console"), True),
            "enable_config_admin_console": _as_bool(features.get("enable_config_admin_console"), True),
            "enable_read_apis": _as_bool(features.get("enable_read_apis"), True),
            "enable_mutation_apis": _as_bool(features.get("enable_mutation_apis"), True),
            "show_gateway_settings": _as_bool(features.get("show_gateway_settings"), True),
            "show_api_index": _as_bool(features.get("show_api_index"), True),
        },
        "security": {
            "require_admin_token_for_mutation": _as_bool(security.get("require_admin_token_for_mutation"), True),
        },
    }


def _diff_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return {"changed": changed, "changed_count": len(changed)}


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    section = payload.get(key)
    return dict(section) if isinstance(section, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _source_map_from_payload(payload: dict[str, Any], source: str) -> dict[str, str]:
    source_map: dict[str, str] = {}
    for section_name in ("ui", "features", "security"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for key in section:
            source_map[f"{section_name}.{key}"] = source
    return source_map


def _safe_choice(value: Any, allowed: set[str], default: str, warnings: list[str], path: str) -> str:
    text = str(value or "").strip()
    if text in allowed:
        return text
    warnings.append(f"{path} is invalid; using {default}")
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _env_bool(name: str, legacy_name: str | None = None) -> bool | None:
    value = get_compat_env(name, legacy_name)
    if value is None:
        return None
    return _as_bool(value, False)
