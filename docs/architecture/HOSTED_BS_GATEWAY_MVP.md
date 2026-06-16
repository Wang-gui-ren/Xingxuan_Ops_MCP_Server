# 托管 B/S 网关 MVP 说明

本文件保留 `星璇运维MCP` 托管 B/S 网关的 MVP 背景说明，供架构回溯使用。

## 当前结论

- MVP 已演进为当前的本地托管网关实现。
- 当前正式入口为 `xingxuan-mcp-web-gateway`。
- 当前正式写请求头为 `X-XINGXUAN-MCP-Admin-Token`。
- 当前正式页面为：
  - `/approvals`
  - `/config-admin`
  - `/gateway-settings`

## 历史兼容说明

- 旧入口 `tmp-mcp-web-gateway` 仍保留兼容。
- 旧请求头 `X-TMP-MCP-Admin-Token` 仍保留兼容。
- 旧环境变量 `TMP_MCP_*` 仍保留兼容。

## 当前源码位置

- `src/mcp_ops_server/web/gateway.py`
- `src/mcp_ops_server/web_gateway.py`
- `src/mcp_ops_server/web/approval_console.py`
- `src/mcp_ops_server/web/config_admin_console.py`
- `src/mcp_ops_server/web/gateway_settings.py`
- `src/mcp_ops_server/web/gateway_launcher.py`
