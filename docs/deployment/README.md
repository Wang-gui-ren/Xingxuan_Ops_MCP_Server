# 部署说明

本目录收纳 `星璇运维MCP` 的部署样例与入口文档。

## 主要文件

- [DEPLOY_KYLIN_V11.md](DEPLOY_KYLIN_V11.md)
  Linux / 麒麟高级服务器版 V11 参考部署说明。
- `../../packaging/systemd/xingxuan-mcp-ops.service`
  MCP Server systemd 参考服务。
- `../../packaging/sudoers/xingxuan-mcp-ops-agent`
  `ops-agent` sudoers allowlist 参考样例。

## 部署命名

推荐部署名称：

- 工作目录：`/opt/xingxuan-mcp`
- 审计目录：`/var/lib/xingxuan-mcp/audit`
- 审批目录：`/var/lib/xingxuan-mcp/approvals`
- 托管临时目录：`/var/tmp/xingxuan_mcp`

## 参考环境变量

```bash
XINGXUAN_MCP_EXECUTION_AGENT_PROFILE=linux-kylin-ops-agent-v1
XINGXUAN_MCP_ENABLE_PRIVILEGED_EXECUTION=false
XINGXUAN_MCP_AUDIT_DIR=/var/lib/xingxuan-mcp/audit
XINGXUAN_MCP_APPROVAL_DIR=/var/lib/xingxuan-mcp/approvals
```

## 兼容说明

- 新部署请使用 `XINGXUAN_MCP_*`
- 历史部署中的 `TMP_MCP_*` 仍可兼容读取
- 仓库中的物理目录名 `tmp_mcp` 不影响线上部署目录命名
