@echo off
set XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN=qingxuan
set TMP_MCP_GATEWAY_ADMIN_TOKEN=%XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN%
set PYTHONPATH=G:\完整mcp\tmp_mcp\src
D:\miniconda\envs\astrbot\python.exe -m mcp_ops_server.web_gateway
