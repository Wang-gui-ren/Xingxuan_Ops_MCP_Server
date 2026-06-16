"""MCP Tool 分组注册入口。

这里不直接实现业务逻辑，只暴露各类 Tool 的注册函数。
拆分分组后，新增工具时可以先判断它属于“采集、诊断、流水线、执行申请”
哪一类，避免继续把所有 `@mcp.tool()` 都堆在单个文件里。
"""

from .approval_tools import register_approval_tools
from .audit_tools import register_audit_tools
from .basic_tools import register_basic_tools
from .config_tools import register_config_tools
from .diagnostic_tools import register_diagnostic_tools
from .execution_tools import register_execution_tools
from .gateway_tools import register_gateway_tools
from .pipeline_tools import register_pipeline_tools

__all__ = [
    "register_basic_tools",
    "register_config_tools",
    "register_approval_tools",
    "register_audit_tools",
    "register_diagnostic_tools",
    "register_execution_tools",
    "register_gateway_tools",
    "register_pipeline_tools",
]
