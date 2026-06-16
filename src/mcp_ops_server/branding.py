from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PRODUCT_NAME = "星璇运维MCP"
PRODUCT_MARK = "星璇"
TECHNICAL_NAME = "xingxuan-mcp"
LEGACY_TECHNICAL_NAME = "tmp-mcp"

ENV_PREFIX = "XINGXUAN_MCP_"
LEGACY_ENV_PREFIX = "TMP_MCP_"

SERVER_NAME = f"{TECHNICAL_NAME}-ops-server"
LEGACY_SERVER_NAME = f"{LEGACY_TECHNICAL_NAME}-ops-server"
WEB_GATEWAY_NAME = f"{TECHNICAL_NAME}-web-gateway"
LEGACY_WEB_GATEWAY_NAME = f"{LEGACY_TECHNICAL_NAME}-web-gateway"
HOSTED_GATEWAY_SERVICE = f"{TECHNICAL_NAME}-hosted-bs-gateway"
LEGACY_HOSTED_GATEWAY_SERVICE = f"{LEGACY_TECHNICAL_NAME}-hosted-bs-gateway"
DEFAULT_TRACE_PREFIX = f"{TECHNICAL_NAME}-local"
LEGACY_TRACE_PREFIX = f"{LEGACY_TECHNICAL_NAME}-local"
HTTP_USER_AGENT = f"{SERVER_NAME}/0.1"
LEGACY_HTTP_USER_AGENT = f"{LEGACY_SERVER_NAME}/0.1"

ADMIN_TOKEN_HEADER = "X-XINGXUAN-MCP-Admin-Token"
LEGACY_ADMIN_TOKEN_HEADER = "X-TMP-MCP-Admin-Token"
SESSION_COOKIE_NAME = f"{TECHNICAL_NAME}-session"
LEGACY_SESSION_COOKIE_NAME = f"{LEGACY_TECHNICAL_NAME}-session"
UI_LOCALE_STORAGE_KEY = "xingxuan_mcp_ui_locale"
LEGACY_UI_LOCALE_STORAGE_KEY = "tmp_mcp_ui_locale"
UI_STYLE_NAME = "xingxuan_mcp"
LEGACY_UI_STYLE_NAME = "tmp_mcp"

DEFAULT_WINDOWS_MANAGED_ROOT = Path(r"C:\ProgramData\xingxuan_mcp")
DEFAULT_LINUX_MANAGED_ROOT = Path("/var/tmp/xingxuan_mcp")
MANAGED_ROOT_ENV = "XINGXUAN_MCP_MANAGED_ROOT"
LEGACY_MANAGED_ROOT_ENV = "TMP_MCP_MANAGED_ROOT"

FILESYSTEM_PLUGIN_ID = "astrbot_plugin_xingxuan_mcp_filesystem"
LEGACY_FILESYSTEM_PLUGIN_ID = "astrbot_plugin_tmp_mcp_filesystem"
APPROVALS_PLUGIN_ID = "astrbot_plugin_xingxuan_mcp_approvals"
LEGACY_APPROVALS_PLUGIN_ID = "astrbot_plugin_tmp_mcp_approvals"


def preferred_env_name(name: str) -> str:
    if name.startswith(LEGACY_ENV_PREFIX):
        return ENV_PREFIX + name[len(LEGACY_ENV_PREFIX) :]
    return name


def legacy_env_name(name: str) -> str | None:
    if name.startswith(ENV_PREFIX):
        return LEGACY_ENV_PREFIX + name[len(ENV_PREFIX) :]
    if name.startswith(LEGACY_ENV_PREFIX):
        return name
    return None


def get_prefixed_env(name: str, default: Any = None) -> Any:
    preferred = preferred_env_name(name)
    preferred_value = os.environ.get(preferred)
    if preferred_value is not None:
        return preferred_value
    legacy = legacy_env_name(name)
    if legacy is not None:
        legacy_value = os.environ.get(legacy)
        if legacy_value is not None:
            return legacy_value
    return default


def get_prefixed_env_source(name: str) -> str | None:
    preferred = preferred_env_name(name)
    if preferred in os.environ:
        return preferred
    legacy = legacy_env_name(name)
    if legacy is not None and legacy in os.environ:
        return legacy
    return None


def get_compat_env(primary: str, legacy: str | None = None, default: Any = None) -> Any:
    value = os.environ.get(primary)
    if value is not None:
        return value
    if legacy is not None:
        legacy_value = os.environ.get(legacy)
        if legacy_value is not None:
            return legacy_value
    return default


def get_compat_env_source(primary: str, legacy: str | None = None) -> str | None:
    if primary in os.environ:
        return primary
    if legacy is not None and legacy in os.environ:
        return legacy
    return None


def version_matches(value: Any, current: str, legacy: str | None = None) -> bool:
    if value is None:
        return False
    text = str(value)
    if text == current:
        return True
    return legacy is not None and text == legacy
