from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.branding import SERVER_NAME
from mcp_ops_server.prompts import register_prompts
from mcp_ops_server.resources import register_resources
from mcp_ops_server.tools import register_tools


def create_server() -> FastMCP:
    mcp = FastMCP(SERVER_NAME)
    register_resources(mcp)
    register_tools(mcp)
    register_prompts(mcp)
    return mcp
