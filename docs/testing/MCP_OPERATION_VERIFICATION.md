# MCP 运行验收

## 目标

本验收文档用于确认 `星璇运维MCP` 在品牌迁移后仍满足以下要求：

- 新品牌和新技术标识已经对外生效
- 旧环境变量和旧请求头仍可兼容
- 审批台、配置台、网关设置页正常可用
- 安装脚本、验证脚本、部署样例与文档口径一致

## 核心检查项

| 编号 | 检查项 | 预期 |
| --- | --- | --- |
| BR-001 | 全仓搜索 `tmp-MCP` | 仅出现在兼容层、迁移说明或必要 legacy 注释 |
| BR-002 | 全仓搜索 `tmp-mcp-web-gateway` | 仅保留兼容入口或迁移说明 |
| BR-003 | 审批台标题 | 显示 `星璇运维MCP Approval Console` / `星璇运维MCP 审批台` |
| BR-004 | 配置台标题 | 显示 `星璇运维MCP Config Admin` / `星璇运维MCP 配置管理` |
| BR-005 | 网关设置页标题 | 显示 `星璇运维MCP Gateway Settings` |
| BR-006 | 新请求头 | `X-XINGXUAN-MCP-Admin-Token` 可调用写接口 |
| BR-007 | 旧请求头 | `X-TMP-MCP-Admin-Token` 仍可被后端接受 |
| BR-008 | 新 locale 键 | 页面写入 `xingxuan_mcp_ui_locale` |
| BR-009 | 旧 locale 键迁移 | 首屏可回退读取 `tmp_mcp_ui_locale` |
| BR-010 | 新 Cookie | `xingxuan-mcp-session` 生效 |
| BR-011 | 旧 Cookie | `tmp-mcp-session` 仍兼容读取 |
| BR-012 | 新插件 ID | 安装脚本默认使用 `astrbot_plugin_xingxuan_mcp_*` |
| BR-013 | 旧插件 ID | 旧安装目录仍可被校验脚本识别 |

## 推荐验证命令

```powershell
cd G:\完整mcp\tmp_mcp
python -m compileall -q src\mcp_ops_server scripts
python .\scripts\verify_approval_console.py
python .\scripts\verify_approval_identity_config.py
python .\scripts\verify_web_gateway.py
python .\scripts\verify_astrbot_ops_bridge_install.py
```

## 手工检查

### 网关页面

1. 启动 `xingxuan-mcp-web-gateway`
2. 打开 `/approvals`
3. 打开 `/config-admin`
4. 打开 `/gateway-settings`

预期：

- 页面头部全部是 `星璇运维MCP`
- 语言切换能在中英文之间切换
- 写操作由管理员令牌保护

### 兼容性抽查

1. 仅设置 `XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN`
2. 验证写接口正常
3. 改为仅设置 `TMP_MCP_GATEWAY_ADMIN_TOKEN`
4. 验证写接口仍正常

### AstrBot 插件

1. 安装文件系统插件
2. 安装审批插件
3. 检查插件目录名默认值是否为 `astrbot_plugin_xingxuan_mcp_*`
4. 抽查旧目录名在历史环境中的识别情况

## 迁移结论模板

可在验收后记录如下结论：

```text
星璇运维MCP 品牌迁移完成。
新品牌、新请求头、新 cookie、新 locale 键和新插件 ID 已生效。
旧 TMP_MCP_*、旧请求头、旧 cookie 和旧插件 ID 兼容正常。
物理目录 tmp_mcp 与 Python 包 mcp_ops_server 保持不变。
```
