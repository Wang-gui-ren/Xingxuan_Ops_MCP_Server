# PR-E B/S 身份可信配置管理台预开发文档

## 实现状态（2026-06-10）

PR-E 已完成第一版代码落地，当前能力不再停留在方案层：

- 新增 `tmp_MCP/config/approval_identity.json`，作为 MCP 自己的身份可信配置模板。
- 新增 `src/mcp_ops_server/config/approval_identity.py`，统一处理默认值、JSON 配置文件、local JSON、环境变量覆盖、脱敏输出、fingerprint、配置校验、原子写入和管理员身份断言。
- `approvals/external.py` 已改为读取有效配置；环境变量仍保持最高优先级，因此旧部署方式继续兼容。
- 新增 `tool_groups/config_tools.py`，注册配置管理工具：
  - `get_approval_identity_config_tool`
  - `validate_approval_identity_config_tool`
  - `update_approval_identity_config_tool`
  - `rotate_approval_identity_secret_tool`
  - `get_config_admin_console_bundle_tool`
- 新增 `web/config_admin_console.py`，输出 `config-admin-console-bundle-v1` 和自包含 HTML；托管页面已按 Semi Design 的 Card、Form、Input、TextArea、Button、Tag 和 Timeline 组件语义重写，并支持中文/英文热切换。
- 新增 `scripts/verify_approval_identity_config.py`，专项验证配置查询、脱敏、dry-run、管理员断言、配置更新、密钥轮换、HTML bundle、审计事件和审批身份函数集成。
- `scripts/verify_mcp_operations.py` 已接入 `register_config_tools()`，并新增 `approval_identity_config_view` 总体验证用例。
- 新增 `web/gateway.py` 和 `web_gateway.py`，完成托管式 B/S 审批/配置网关 MVP，可直接打开 `/approvals`、`/config-admin` 与 `/gateway-settings`。
- 新增 `config/web_gateway.json`、`config/web_gateway.py` 和 `web/gateway_settings.py`，支持通过项目内配置和 B/S 设置页控制默认入口、页面开关、只读 API、业务写 API、设置页和路由索引；页面主操作采用 Semi Design 风格的 Card、Form、RadioGroup、Switch、Button 和 Tag，不要求管理员手写 JSON，并支持中文/英文热切换；功能开关在语言重绘后会重新绑定事件，状态统计包含安全令牌开关，并覆盖 Semi 原生 switch 宽度以避免中文标题竖排。
- 审批控制台和配置管理台的页面按钮已可在托管式 HTTP 模式下调用受控 API，分别映射到审批 token 签发、审批落账、配置校验和配置更新工具。
- 新增 `scripts/verify_web_gateway.py`，专项验证网关健康检查、路由清单、页面渲染、只读 API、脱敏边界、管理员 token 写接口闸门、网关选项校验、热更新、业务写 API 开关、审批台中文/英文热切换、审批队列搜索框与筛选按钮布局、审批页脚本转义、配置页 Semi Design shell/Form/Input、设置页开关控件、分段控件、功能开关重绘事件重绑、中文开关统计文案、Semi switch 卡片宽度覆盖、中文标题防竖排、Semi Design shell、Semi 资源引用和可访问 `switch` 角色。
- Semi Design 组件文档可通过开发期 `semi-mcp` 查询，推荐 MCP 配置为 `npx -y @douyinfe/semi-mcp`，内网可替换为 `@ies/semi-mcp-bytedance`；该 MCP 不作为 `tmp_MCP` 运行时依赖。

本次实现仍不触碰 `C:\Users\Yang\.codex\auth.json` 和 `C:\Users\Yang\.codex\config.toml`；配置前端只管理 `tmp_MCP` 内部专用配置。

当前验证结果：

```powershell
D:\miniconda\envs\astrbot\python.exe -m compileall -q tmp_MCP\src\mcp_ops_server tmp_MCP\scripts
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_identity_config.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_identity.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_console.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_review_packet.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_web_gateway.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_execution_agent_profiles.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_mcp_operations.py
```

通过结果：

- `verify_approval_identity_config.py`：31 / 31 PASS
- `verify_approval_identity.py`：15 / 15 PASS
- `verify_approval_console.py`：25 / 25 PASS
- `verify_approval_review_packet.py`：13 / 13 PASS
- `verify_web_gateway.py`：88 / 88 PASS
- `verify_execution_agent_profiles.py`：33 / 33 PASS
- `verify_mcp_operations.py`：60 / 60 PASS

本文档承接 `PR_D_APPROVAL_UI_AND_IDENTITY_PREDEV.md`。PR-D 已经把 B/S 审批控制台 bundle、企业身份断言和审批 token 签发链路接入 MCP 审批账本；PR-E 的目标是继续推进“配置也可被受控管理”，让管理员可以通过前端界面查看和更新 MCP 自己的身份可信配置。

当前阶段已经完成配置模型、MCP 工具契约、前端页面 bundle、托管式 B/S 网关 MVP 和验证脚本。后续生产级开发仍必须只修改 `tmp_MCP` 内部文件，不应触碰 `C:\Users\Yang\.codex\auth.json`、`C:\Users\Yang\.codex\config.toml` 或其他 Codex 凭据文件。

## 背景

当前身份可信模式主要通过环境变量打开：

```powershell
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY="true"
$env:TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE="true"
$env:TMP_MCP_APPROVAL_IDENTITY_SECRET="..."
$env:TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER="true"
$env:TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET="..."
$env:TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS="approval-gateway"
$env:TMP_MCP_ENTERPRISE_APPROVER_ROLE="ops_approver"
```

这种方式适合本地验证和部署脚本，但不适合企业管理员日常操作。PR-E 需要提供一个受控配置入口，让管理员能在 B/S 管理界面完成以下动作：

- 查看身份可信模式是否开启。
- 查看企业 token 签发模式是否开启。
- 维护 issuer allowlist 和审批人必需角色。
- 查看密钥是否已配置、密钥指纹和最近轮换时间。
- 提交配置变更，并进入审计日志。
- 明确哪些变更需要重启，哪些未来可以热加载。

## 总体结论

可以做前端配置页，但前端不能直接编辑任意配置文件，也不能直接读取或展示明文密钥。

推荐链路：

```text
B/S 配置页
-> 受控 MCP 管理工具
-> 后端权限校验和参数校验
-> 写入 tmp_MCP 专用配置文件
-> 记录审计事件
-> 返回 restart_required / reload_result
```

不推荐链路：

```text
B/S 配置页
-> 直接修改 C:\Users\Yang\.codex\auth.json
-> 直接修改 C:\Users\Yang\.codex\config.toml
-> 直接展示或回传明文 secret
```

## 目标

1. 新增 MCP 自己的身份可信配置文件，例如 `tmp_MCP/config/approval_identity.json`。
2. 新增配置读取层，统一处理默认值、配置文件和环境变量覆盖。
3. 新增只读配置查询工具，返回脱敏后的配置状态。
4. 新增配置校验工具，在写入前进行 dry-run。
5. 新增管理员配置更新工具，更新配置时写入审计事件。
6. 新增密钥轮换入口，只展示密钥状态和指纹，不回显明文密钥。
7. 为未来 B/S 网关提供页面状态 bundle。

## 非目标

本阶段不做以下事情：

- 不修改 `C:\Users\Yang\.codex\auth.json`。
- 不修改 `C:\Users\Yang\.codex\config.toml`。
- 不把生产密钥明文提交到仓库。
- 不让普通审批人或普通用户修改安全配置。
- 不用配置页绕过 `record_operation_approval_tool`、`issue_enterprise_approval_token_tool` 或审批账本。
- 不替代正式 IAM、OIDC、LDAP、KMS、Vault 或企业密钥管理系统。
- 不让前端直接写 JSONL 审批账本或审计日志。

## 配置来源优先级

建议采用以下优先级：

```text
环境变量
> tmp_MCP/config/approval_identity.local.json
> tmp_MCP/config/approval_identity.json
> 代码默认值
```

说明：

- 环境变量优先级最高，便于生产部署平台统一注入。
- `approval_identity.local.json` 用于本地开发，不应提交真实密钥。
- `approval_identity.json` 可提交非敏感默认配置和结构模板。
- 代码默认值必须保持安全：身份强校验默认关闭，企业 token 签发默认关闭。

## 配置文件建议结构

```json
{
  "schema_version": "approval-identity-config-v1",
  "identity": {
    "require_approval_identity": false,
    "require_approval_identity_scope": true,
    "approval_token_ttl_minutes": 15
  },
  "enterprise": {
    "enable_enterprise_approval_token_issuer": false,
    "allowed_issuers": [],
    "required_approver_role": "ops_approver",
    "enterprise_assertion_ttl_minutes": 10
  },
  "secrets": {
    "approval_identity_secret_ref": null,
    "enterprise_identity_assertion_secret_ref": null
  },
  "admin": {
    "require_admin_identity": true,
    "allowed_admin_roles": ["mcp_security_admin"]
  }
}
```

密钥处理建议：

- 生产环境使用 `secret_ref` 指向 KMS、Vault、Windows Credential Manager 或部署平台密钥。
- 本地开发可以用环境变量注入。
- 前端页面只展示 `configured=true/false`、`key_id`、`fingerprint`、`updated_at`、`updated_by`。
- 不提供“查看明文密钥”功能。

## 新增 MCP 工具契约

### get_approval_identity_config_tool

只读查询当前身份可信配置状态。

建议入参：

```json
{
  "include_effective_config": true,
  "include_sources": true
}
```

建议出参：

```json
{
  "ok": true,
  "data": {
    "schema_version": "approval-identity-config-v1",
    "effective_config": {
      "require_approval_identity": true,
      "require_approval_identity_scope": true,
      "enterprise_token_issuer_enabled": true,
      "allowed_issuers": ["approval-gateway"],
      "required_approver_role": "ops_approver"
    },
    "secret_status": {
      "approval_identity_secret": {
        "configured": true,
        "source": "env",
        "fingerprint": "sha256:abcd1234"
      },
      "enterprise_assertion_secret": {
        "configured": true,
        "source": "env",
        "fingerprint": "sha256:ef567890"
      }
    },
    "restart_required": false
  }
}
```

要求：

- 不返回任何明文 secret。
- 普通用户不可调用。
- 查询也写入低风险审计事件，至少记录调用人、trace_id 和配置来源摘要。

### validate_approval_identity_config_tool

校验配置 patch，但不写入。

建议入参：

```json
{
  "config_patch": {
    "identity": {
      "require_approval_identity": true
    },
    "enterprise": {
      "allowed_issuers": ["approval-gateway"],
      "required_approver_role": "ops_approver"
    }
  }
}
```

建议校验规则：

- `allowed_issuers` 不能为空字符串。
- issuer 只能包含安全字符，例如字母、数字、点、下划线、短横线和冒号。
- `required_approver_role` 不能为空。
- TTL 必须在合理范围内，例如 1 到 1440 分钟。
- 开启企业 token 签发时，必须存在企业 assertion secret。
- 开启审批身份强校验时，必须存在 approval identity secret。

### update_approval_identity_config_tool

写入配置变更。

建议入参：

```json
{
  "config_patch": {
    "identity": {
      "require_approval_identity": true,
      "require_approval_identity_scope": true
    }
  },
  "admin_approver": "security-admin",
  "admin_identity_assertion": {
    "issuer": "approval-gateway",
    "subject": "security-admin@example.com",
    "roles": ["mcp_security_admin"]
  },
  "change_reason": "enable identity trusted mode for approval ledger"
}
```

要求：

- 必须验证管理员身份。
- 必须先执行与 `validate_approval_identity_config_tool` 相同的校验。
- 必须原子写入配置文件。
- 必须写入审计事件。
- 返回变更 diff、配置版本、是否需要重启。

### rotate_approval_identity_secret_tool

轮换审批身份密钥或企业 assertion 密钥。

建议入参：

```json
{
  "secret_kind": "approval_identity_secret",
  "new_secret_ref": "kms://tmp-mcp/approval-identity/2026-06",
  "admin_approver": "security-admin",
  "admin_identity_assertion": {
    "issuer": "approval-gateway",
    "subject": "security-admin@example.com",
    "roles": ["mcp_security_admin"]
  },
  "change_reason": "scheduled key rotation"
}
```

要求：

- 不回显明文 secret。
- 返回新 key_id、fingerprint 和生效状态。
- 审计事件应记录 secret_kind、old_fingerprint、new_fingerprint、updated_by。
- 后续可扩展密钥双写窗口、旧 token 宽限期和撤销列表。

### get_config_admin_console_bundle_tool

给 B/S 配置页面返回只读页面 bundle。

建议返回：

```text
config_bundle.schema_version=config-admin-console-bundle-v1
config_bundle.state.effective_config
config_bundle.state.secret_status
config_bundle.state.audit_events
config_bundle.state.mcp_contract
config_bundle.html
```

该工具本身只读，不写配置、不轮换密钥。

## 前端页面设计

建议未来 B/S 网关提供以下页面：

```text
/approvals
/approvals/{approval_id}
/settings/identity
/settings/policy
/audit
```

其中 `/settings/identity` 是 PR-E 的重点页面。

### 页面区域

1. 身份可信总览
   - 身份强校验是否开启。
   - scope 绑定是否开启。
   - 企业 token 签发是否开启。
   - 当前配置来源。
   - 是否需要重启。

2. 企业身份配置
   - issuer allowlist。
   - 审批人必需角色。
   - token TTL。
   - assertion TTL。

3. 密钥状态
   - 是否已配置。
   - 来源：env、local file、secret_ref。
   - 指纹。
   - 最近更新时间。
   - 轮换入口。

4. 变更预览
   - 展示 patch diff。
   - 显示校验结果。
   - 显示风险提示。
   - 显示是否需要重启。

5. 审计时间线
   - 配置查询。
   - 配置校验。
   - 配置更新。
   - 密钥轮换。
   - 配置加载失败。

### UX 约束

- 保存按钮只在校验通过后可用。
- 涉及关闭身份强校验、关闭 scope 绑定、清空 issuer allowlist 的变更必须二次确认。
- 页面不出现明文 secret。
- 复制按钮只能复制配置摘要、fingerprint 或 key_id。
- 页面文字应偏运维管理台风格，不做营销化首页。

## 权限模型

建议划分三类角色：

| 角色 | 权限 |
| --- | --- |
| 普通用户 | 创建审批申请，查看自己相关审批 |
| 审批人 | 查看审批队列，grant/reject 审批 |
| 安全管理员 | 查看和更新身份可信配置，轮换密钥 |

工具暴露建议：

```text
普通用户:
request_operation_approval_tool
get_operation_approval_tool

审批人:
get_approval_review_packet_tool
get_approval_console_bundle_tool
issue_enterprise_approval_token_tool
record_operation_approval_tool

安全管理员:
get_approval_identity_config_tool
validate_approval_identity_config_tool
update_approval_identity_config_tool
rotate_approval_identity_secret_tool
get_config_admin_console_bundle_tool
```

## 审计事件

建议新增事件类型：

```text
approval_identity_config_viewed
approval_identity_config_validated
approval_identity_config_update_denied
approval_identity_config_updated
approval_identity_secret_rotation_denied
approval_identity_secret_rotated
approval_identity_config_reload_requested
approval_identity_config_reload_failed
```

每条事件至少包含：

- `trace_id`
- `session_id`
- `admin_approver`
- `admin_identity_summary`
- `config_version`
- `change_reason`
- `diff_summary`
- `restart_required`

## 安全边界

1. 前端页面不直接写文件。
2. 前端页面不直接读 secret。
3. 配置写入必须通过 MCP 管理工具。
4. 管理工具必须验证管理员身份。
5. 配置变更必须审计。
6. 密钥轮换必须脱敏。
7. 环境变量覆盖必须在页面中明确展示为只读来源。
8. `auth.json` 和 Codex `config.toml` 不属于本功能管理范围。
9. 配置管理功能不能绕过审批账本。
10. 生产环境必须由真实 B/S 网关、IAM、OIDC、KMS 或企业密钥系统承接身份和密钥。

## 开发阶段拆分

### 阶段 1：配置模型和读取层

- 新增 `src/mcp_ops_server/config/approval_identity.py`。
- 定义配置 dataclass。
- 支持默认值、JSON 文件、local JSON 和环境变量覆盖。
- 支持脱敏输出。
- 支持 fingerprint 计算。

### 阶段 2：配置管理 MCP 工具

- 新增 `tool_groups/config_tools.py` 或扩展审批工具组。
- 实现只读查询、dry-run 校验和配置更新。
- 写入审计事件。
- 保证无明文 secret 泄漏。

### 阶段 3：配置页面 bundle

- 新增 `src/mcp_ops_server/web/config_admin_console.py`。
- 返回 `config-admin-console-bundle-v1`。
- 页面展示配置状态、密钥状态、变更预览和审计时间线。
- 页面只提供动作契约，不直接落账。

### 阶段 4：验证脚本

- 新增 `scripts/verify_approval_identity_config.py`。
- 覆盖配置加载、环境变量覆盖、校验失败、成功更新、审计事件和脱敏输出。
- 加入 `verify_mcp_operations.py` 端到端验证。

### 阶段 5：托管式 B/S 网关

- 已新增 `src/mcp_ops_server/web/gateway.py`，消费 `get_approval_console_bundle_tool` 与 `get_config_admin_console_bundle_tool`。
- 已新增 `src/mcp_ops_server/web_gateway.py`，支持 `python -m mcp_ops_server.web_gateway --host 127.0.0.1 --port 8765 --options-file config/web_gateway.json` 启动。
- 已新增 `config/web_gateway.py`、`config/web_gateway.json` 和 `web/gateway_settings.py`，支持项目内网关选项加载、校验、原子写入和 B/S 设置页面。
- 已提供 `/approvals`、`/config-admin` 与 `/gateway-settings` 页面，并提供 `/api/approval-console`、`/api/config-admin-console`、`/api/gateway/options` 只读 JSON API。
- 已提供 `/api/gateway/options/validate` 与 `/api/gateway/options/update`，设置更新仍以 `TMP_MCP_GATEWAY_ADMIN_TOKEN` 为本地管理员 token 闸门。
- 已将页面按钮映射到受控 MCP 工具：审批写入走 `issue_enterprise_approval_token_tool` 与 `record_operation_approval_tool`，配置写入走 `validate_approval_identity_config_tool` 与 `update_approval_identity_config_tool`。
- 写接口以 `TMP_MCP_GATEWAY_ADMIN_TOKEN` 为本地管理员 token 闸门；未配置 token 时只读页面可打开，写接口拒绝。
- 仍待补齐生产级登录态、CSRF、防重放、服务端会话管理、企业管理员角色校验、token 撤销和 OIDC/IAM/KMS 接入。

## 验证用例

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| CFG-001 | 查询配置 | 返回脱敏配置，不包含明文 secret |
| CFG-002 | 环境变量覆盖文件配置 | effective_config 以环境变量为准 |
| CFG-003 | 开启身份强校验但无 identity secret | dry-run 失败，不写文件 |
| CFG-004 | 开启企业 token 签发但无 assertion secret | dry-run 失败，不写文件 |
| CFG-005 | issuer 包含非法字符 | 校验失败 |
| CFG-006 | 普通用户尝试更新配置 | 拒绝并写入 denied 审计 |
| CFG-007 | 安全管理员更新 issuer allowlist | 写入配置，返回 diff 和审计事件 |
| CFG-008 | 密钥轮换 | 不回显明文，只返回 fingerprint |
| CFG-009 | 配置页面 bundle | 返回 `config-admin-console-bundle-v1` 和可渲染 HTML |
| CFG-010 | 配置更新后审批链路 | `verify_approval_identity.py` 和 `verify_approval_console.py` 仍通过 |
| CFG-011 | 托管式网关只读页面 | `/approvals` 与 `/config-admin` 可打开且不回显明文 secret |
| CFG-012 | 托管式网关写接口 | 无管理员 token 拒绝，携带 token 后才进入受控 MCP 工具 |
| CFG-013 | 网关设置页 | `/gateway-settings` 可打开，能展示当前 options、路由状态、Semi Design 开关卡片、RadioGroup 分段控件、Button 操作区、Tag 状态和 patch 预览 |
| CFG-014 | 网关选项更新 | 无管理员 token 拒绝，携带 token 后可热更新默认入口、页面和 API 开关 |

## AstrBot 手工测试文案

### 查询配置状态

```text
只允许通过 MCP 工具调用，不要使用 shell。请调用 get_approval_identity_config_tool 查询当前身份可信配置，说明是否开启审批身份强校验、是否开启 scope 绑定、是否开启企业 token 签发、允许的 issuer、审批人必需角色，以及返回结果中是否没有明文 secret。
```

### 校验错误配置

```text
只允许通过 MCP 工具调用，不要使用 shell。请调用 validate_approval_identity_config_tool，尝试把 enable_enterprise_approval_token_issuer 设置为 true，同时不给 enterprise assertion secret。预期应该校验失败，并说明为什么不能写入配置。
```

### 管理员更新配置

```text
只允许通过 MCP 工具调用，不要使用 shell。以安全管理员身份调用 update_approval_identity_config_tool，把 allowed_issuers 设置为 ["approval-gateway"]，required_approver_role 设置为 "ops_approver"，change_reason 为“接入受信审批网关”。请说明返回的 diff、restart_required 和审计事件。
```

### 密钥状态检查

```text
只允许通过 MCP 工具调用，不要使用 shell。请查询身份可信配置中的 secret_status，确认页面或工具返回值只包含 configured、source、fingerprint、updated_at，不包含任何明文 secret。
```

## 完成标准

PR-E 完成后应满足：

- 管理员可以通过 MCP 工具查询脱敏后的身份可信配置。
- 管理员可以 dry-run 校验配置变更。
- 管理员可以受控写入 `tmp_MCP` 专用配置。
- 所有配置变更都进入审计日志。
- 明文 secret 不出现在工具返回、HTML bundle、审计日志或 human_report 中。
- `auth.json` 和 Codex `config.toml` 不被读取、不被写入、不被展示。
- 现有审批身份链路和审批控制台验证脚本继续通过。
- 托管式 B/S 网关 MVP 可打开审批页、配置页和网关设置页，并通过管理员 token 闸门调用受控写 API。
- 网关选项只写入 `tmp_MCP/config/web_gateway.json` 或 `--options-file` 指定的项目内文件，不读取、不修改 Codex 凭据配置。

## 推荐下一步

当前阶段 1 到阶段 5 的 MVP 均已完成，且已补齐本地网关选项控制台。下一步优先做生产级网关增强：

```text
托管式 B/S 网关 MVP
-> OIDC/IAM 登录态与服务端会话
-> CSRF / 防重放 / token 撤销
-> KMS / secret resolver
-> 集中审计与权限菜单
```

这一步完成后，当前本地管理员 token 闸门才能升级为企业级身份边界；配置页和审批页也能从本地 MVP 进入可联调的生产网关形态。
