from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.approvals import ApprovalStore
from mcp_ops_server.audit import AuditLogger
from mcp_ops_server.tool_groups import (
    register_approval_tools,
    register_audit_tools,
    register_basic_tools,
    register_config_tools,
    register_diagnostic_tools,
    register_execution_tools,
    register_gateway_tools,
    register_pipeline_tools,
)


def register_tools(mcp: FastMCP) -> None:
    """统一装配所有 MCP Tools。

    `server.py` 只需要调用这个入口；具体工具按组件分散在 `tool_groups/` 中。
    这样既保持 AstrBot/MCP 对外兼容，也让后续新增工具时更容易定位职责边界。
    """

    audit_logger = AuditLogger()
    approval_store = ApprovalStore()

    register_basic_tools(mcp)
    register_diagnostic_tools(mcp)
    register_pipeline_tools(mcp)
    register_audit_tools(mcp, audit_logger=audit_logger)
    register_approval_tools(mcp, approval_store=approval_store, audit_logger=audit_logger)
    register_config_tools(mcp, audit_logger=audit_logger)
    register_gateway_tools(mcp, audit_logger=audit_logger)
    register_execution_tools(mcp, audit_logger=audit_logger, approval_store=approval_store)
