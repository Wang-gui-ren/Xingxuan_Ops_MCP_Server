# 使用说明

## 适用范围

本说明面向 `星璇运维MCP` 的日常使用者、审批人和集成人员，重点覆盖：

- MCP Server 启动
- 本地托管网关使用
- 审批台、配置台、网关设置页
- 新旧品牌兼容关系

## 启动方式

启动 MCP Server：

```powershell
cd G:\完整mcp\tmp_mcp
xingxuan-mcp-ops-server
```

启动 Web Gateway：

```powershell
$env:XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN = "change-me-local-admin-token"
xingxuan-mcp-web-gateway
```

兼容入口仍可用：

```powershell
tmp-mcp-ops-server
tmp-mcp-web-gateway
```

## 主要页面

### 审批台

地址：`/approvals`

用途：

- 查看审批队列
- 查看审批详情和审计线索
- 通过网关调用审批决策接口
- 在需要时附带企业身份断言签发 `approval_token`

### 配置管理页

地址：`/config-admin`

用途：

- 查看审批身份配置的生效状态
- 预览配置校验和更新结果
- 查看审计生产化指标
- 触发审计轮转与锚点同步

### 网关设置页

地址：`/gateway-settings`

用途：

- 控制默认入口页面
- 控制 UI 风格和密度
- 控制审批页、配置页、只读 API、写 API 和设置页开关

## 网关鉴权

### 写接口

主请求头：

```text
X-XINGXUAN-MCP-Admin-Token: <XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN>
```

兼容旧请求头：

```text
X-TMP-MCP-Admin-Token: <TMP_MCP_GATEWAY_ADMIN_TOKEN>
```

也支持：

```text
Authorization: Bearer <token>
```

### Session Cookie

主 Cookie：

```text
xingxuan-mcp-session
```

兼容旧 Cookie：

```text
tmp-mcp-session
```

## 常用环境变量

### 网关

```powershell
$env:XINGXUAN_MCP_GATEWAY_HOST = "127.0.0.1"
$env:XINGXUAN_MCP_GATEWAY_PORT = "8765"
$env:XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN = "change-me"
$env:XINGXUAN_MCP_GATEWAY_QUIET = "true"
$env:XINGXUAN_MCP_WEB_GATEWAY_CONFIG_FILE = "G:\完整mcp\tmp_mcp\config\web_gateway.json"
```

### 审批

```powershell
$env:XINGXUAN_MCP_APPROVAL_DIR = "G:\完整mcp\tmp_mcp\data\approvals"
$env:XINGXUAN_MCP_APPROVAL_POLICY_FILE = "G:\完整mcp\tmp_mcp\config\approvals\policies.yaml"
$env:XINGXUAN_MCP_APPROVAL_ANCHOR_SECRET = "change-me"
```

### 审计

```powershell
$env:XINGXUAN_MCP_AUDIT_DIR = "G:\完整mcp\tmp_mcp\data\audit"
$env:XINGXUAN_MCP_AUDIT_ANCHOR_SECRET = "change-me"
$env:XINGXUAN_MCP_AUDIT_ANCHOR_HTTP_URL = "https://example.invalid/anchors"
```

### 审批身份

```powershell
$env:XINGXUAN_MCP_APPROVAL_IDENTITY_CONFIG_FILE = "G:\完整mcp\tmp_mcp\config\approval_identity.json"
$env:XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY = "true"
$env:XINGXUAN_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE = "true"
$env:XINGXUAN_MCP_APPROVAL_IDENTITY_SECRET = "change-me"
$env:XINGXUAN_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER = "true"
$env:XINGXUAN_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET = "change-me"
$env:XINGXUAN_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS = "corp-idp"
$env:XINGXUAN_MCP_ENTERPRISE_APPROVER_ROLE = "ops_approver"
```

### 执行代理

```powershell
$env:XINGXUAN_MCP_EXECUTION_AGENT_PROFILE = "linux-kylin-ops-agent-v1"
$env:XINGXUAN_MCP_ENABLE_PRIVILEGED_EXECUTION = "false"
$env:XINGXUAN_MCP_TRUSTED_EXECUTION_IDENTITIES = "ops-agent"
```

## AstrBot 插件

新的默认插件 ID：

- `astrbot_plugin_xingxuan_mcp_filesystem`
- `astrbot_plugin_xingxuan_mcp_approvals`

安装脚本：

```powershell
python .\scripts\install_astrbot_filesystem_plugin.py --astrbot-plugins-dir G:\完整mcp\tmp_astrbot\data\plugins
python .\scripts\install_astrbot_approvals_plugin.py --astrbot-plugins-dir G:\完整mcp\tmp_astrbot\data\plugins
```

旧插件 ID 仍可被旧部署识别，但新安装建议统一使用新 ID。

## 品牌迁移与兼容说明

### 兼容优先级

```text
XINGXUAN_MCP_* > TMP_MCP_* > 默认值
```

### 常见映射

| 新标识 | 旧标识 |
| --- | --- |
| `XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN` | `TMP_MCP_GATEWAY_ADMIN_TOKEN` |
| `X-XINGXUAN-MCP-Admin-Token` | `X-TMP-MCP-Admin-Token` |
| `xingxuan-mcp-session` | `tmp-mcp-session` |
| `xingxuan_mcp_ui_locale` | `tmp_mcp_ui_locale` |
| `xingxuan-mcp-ops-server` | `tmp-mcp-ops-server` |
| `xingxuan-mcp-web-gateway` | `tmp-mcp-web-gateway` |
| `astrbot_plugin_xingxuan_mcp_filesystem` | `astrbot_plugin_tmp_mcp_filesystem` |
| `astrbot_plugin_xingxuan_mcp_approvals` | `astrbot_plugin_tmp_mcp_approvals` |

### 保持不变的内容

- 仓库目录仍是 `tmp_mcp`
- Python 包仍是 `mcp_ops_server`
- 旧环境变量和旧请求头仍然兼容读取
