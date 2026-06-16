# 麒麟 V11 部署参考

## 目标

本文提供 `星璇运维MCP` 在 Linux / 麒麟高级服务器版 V11 上的最小参考部署路径。

## 参考文件

- `packaging/sudoers/xingxuan-mcp-ops-agent`
- `packaging/systemd/xingxuan-mcp-ops.service`

## 目录建议

```text
/opt/xingxuan-mcp
/var/lib/xingxuan-mcp/audit
/var/lib/xingxuan-mcp/approvals
/var/tmp/xingxuan_mcp
```

## sudoers 样例安装

```bash
sudo visudo -cf /opt/xingxuan-mcp/packaging/sudoers/xingxuan-mcp-ops-agent
sudo install -o root -g root -m 0440 /opt/xingxuan-mcp/packaging/sudoers/xingxuan-mcp-ops-agent /etc/sudoers.d/xingxuan-mcp-ops-agent
sudo visudo -cf /etc/sudoers.d/xingxuan-mcp-ops-agent
```

## systemd 样例安装

```bash
sudo install -o root -g root -m 0644 /opt/xingxuan-mcp/packaging/systemd/xingxuan-mcp-ops.service /etc/systemd/system/xingxuan-mcp-ops.service
sudo systemctl daemon-reload
sudo systemctl enable xingxuan-mcp-ops.service
sudo systemctl start xingxuan-mcp-ops.service
sudo systemctl status xingxuan-mcp-ops.service
```

## 推荐环境变量

```bash
XINGXUAN_MCP_EXECUTION_AGENT_PROFILE=linux-kylin-ops-agent-v1
XINGXUAN_MCP_ENABLE_PRIVILEGED_EXECUTION=false
XINGXUAN_MCP_AUDIT_DIR=/var/lib/xingxuan-mcp/audit
XINGXUAN_MCP_APPROVAL_DIR=/var/lib/xingxuan-mcp/approvals
```

## 兼容说明

- 旧 `TMP_MCP_*` 环境变量仍可兼容读取。
- 仓库路径仍可能显示为 `tmp_mcp`，这不影响线上服务名和部署目录。
