# 变更记录

## 2026-06-16

### 品牌迁移

- 对外品牌统一为 `星璇运维MCP`
- 英文技术标识统一为 `xingxuan-mcp`
- 新控制台入口统一为：
  `xingxuan-mcp-ops-server`
  `xingxuan-mcp-web-gateway`
- 新插件默认 ID 统一为：
  `astrbot_plugin_xingxuan_mcp_filesystem`
  `astrbot_plugin_xingxuan_mcp_approvals`

### 兼容层

- 新环境变量前缀切换为 `XINGXUAN_MCP_*`
- 保留 `TMP_MCP_*` 兼容读取
- 新写请求头切换为 `X-XINGXUAN-MCP-Admin-Token`
- 兼容旧请求头 `X-TMP-MCP-Admin-Token`
- 新 cookie 切换为 `xingxuan-mcp-session`
- 兼容旧 cookie `tmp-mcp-session`
- 新 locale 键切换为 `xingxuan_mcp_ui_locale`
- 首屏兼容读取旧键 `tmp_mcp_ui_locale`

### UI 与脚本

- 审批台、配置台、网关设置页和登录页品牌统一切换为 `星璇运维MCP`
- systemd 与 sudoers 样例文件名切换为 `xingxuan-mcp-*`
- AstrBot 插件安装脚本和验证脚本默认值切换到新插件 ID

### 保持不变

- 物理目录仍为 `tmp_mcp`
- Python 包命名空间仍为 `mcp_ops_server`

## 历史说明

更早阶段的大量预研、设计稿和路线图仍保留在 `docs/architecture/`、`docs/planning/` 与 `docs/reports/` 中，用于回溯实现背景；这些历史文档不再作为当前品牌口径的主入口。
