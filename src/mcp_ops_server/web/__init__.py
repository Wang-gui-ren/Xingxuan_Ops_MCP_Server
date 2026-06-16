"""Small embeddable web assets returned by MCP tools."""

from .approval_console import build_approval_console_bundle
from .config_admin_console import build_config_admin_console_bundle
from .gateway_settings import build_gateway_settings_bundle

__all__ = [
    "build_approval_console_bundle",
    "build_config_admin_console_bundle",
    "build_gateway_settings_bundle",
]
