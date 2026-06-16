# 审批增强代码实现方案

本文档把“审批事件模型下一步增强”拆成可以直接编码的任务清单。目标是在不开放任意 shell、不提前放开提权模板的前提下，把当前本地 JSONL 审批账本升级为可撤销、可续期、可清理、可策略约束、可校验篡改的审批子系统。

## 当前进度

截至 2026-06-10，PR-A 生命周期增强、PR-B 审批账本哈希链、PR-C 策略配置/最小多级审批、审批账本外部锚点/可选 HMAC 签名，以及 PR-D 外部审批身份 token 预开发、B/S 审批审核包、B/S 审批控制台 bundle、企业身份断言签发 token、PR-E 配置管理台、托管式 B/S 网关和网关选项控制台已经落地：

- `ApprovalStatus` 已扩展为 `requested / partially_granted / granted / rejected / revoked / expired`。
- `ApprovalRecord` 已增加 schema v3 生命周期、策略和审批人历史字段，并保持旧记录兼容读取。
- 已实现 `revoke_operation_approval_tool`、`renew_operation_approval_tool`、`cleanup_expired_operation_approvals_tool`。
- 已新增 `scripts/verify_approval_lifecycle.py`，并扩展 `scripts/verify_mcp_operations.py`。
- `ApprovalRecord` 新增 `prev_hash / event_hash`，审批 JSONL 账本按追加顺序形成哈希链。
- 已新增 `approvals/verifier.py`、`verify_approval_chain_tool` 和 `scripts/verify_approval_chain.py`。
- 已新增 `config/approvals/policies.yaml`、`approvals/policy.py` 和 `scripts/verify_approval_policy.py`，支持策略 TTL、审批人数、审批角色/白名单、禁止自批、重复审批人拦截和 `partially_granted`。
- 已新增 `approvals/anchor.py`、`anchor_approval_chain_tool`、`verify_approval_anchor_tool` 和 `scripts/verify_approval_anchor.py`，支持审批账本锚点、文件摘要和可选 HMAC-SHA256 签名。
- 已新增 `approvals/external.py`、`record_operation_approval_tool(approval_token=...)` 和 `scripts/verify_approval_identity.py`，支持外部审批身份 token 校验。
- 已新增 `get_approval_review_packet_tool`、`get_approval_console_bundle_tool`、`web/approval_console.py` 和 `scripts/verify_approval_review_packet.py`，支持 B/S 审批页面只读审核包与控制台 bundle。
- 已新增 `issue_enterprise_approval_token_tool` 和企业身份断言校验函数，支持受信企业断言先换短期 `approval_token`，再由 `record_operation_approval_tool` 落账。
- 已新增 `web/gateway.py`、`web_gateway.py`、`web/gateway_settings.py`、`config/web_gateway.py` 和 `scripts/verify_web_gateway.py`，支持本地 HTTP 审批/配置/网关设置页面、受 token 保护的写接口和项目内网关选项控制；配置页和设置页均采用 Semi Design 风格组件语义，并支持中文/英文热切换，功能开关区域在语言重绘后会重新绑定事件、展示本地化统计，并覆盖 Semi 原生 switch 宽度以避免中文标题竖排。
- 当前验证结果：`verify_approval_lifecycle.py` 34 / 34 PASS，`verify_approval_chain.py` 16 / 16 PASS，`verify_approval_policy.py` 32 / 32 PASS，`verify_approval_anchor.py` 17 / 17 PASS，`verify_approval_identity.py` 15 / 15 PASS，`verify_approval_review_packet.py` 13 / 13 PASS，`verify_approval_console.py` 25 / 25 PASS，`verify_web_gateway.py` 88 / 88 PASS。

继续编码时应优先推进真实 OIDC/IAM/KMS 身份接入、服务端会话、CSRF、防重放、签名密钥轮转、token 撤销或真实受限身份执行代理。

## 当前基线

已经具备：

- `src/mcp_ops_server/approvals/store.py`
  - `ApprovalStore`
  - `ApprovalRecord`
  - `ApprovalValidation`
  - `request_approval()`
  - `record_decision()`
  - `validate_approval()`
  - `get_latest()`
  - `list_recent()`
  - `revoke_approval()`
  - `renew_approval()`
  - `mark_expired_approvals()`
- `src/mcp_ops_server/tool_groups/approval_tools.py`
  - `request_operation_approval_tool`
  - `record_operation_approval_tool`
  - `renew_operation_approval_tool`
  - `revoke_operation_approval_tool`
  - `cleanup_expired_operation_approvals_tool`
  - `verify_approval_chain_tool`
  - `anchor_approval_chain_tool`
  - `verify_approval_anchor_tool`
  - `get_operation_approval_tool`
  - `list_operation_approvals_tool`
- `src/mcp_ops_server/approvals/verifier.py`
  - `verify_approval_chain()`
  - `ApprovalChainVerification`
- 审批状态当前包含 `requested / partially_granted / granted / rejected / revoked / expired`。
- 写工具在 `dry_run=false` 时会校验 `approval_id` 是否存在、是否 `granted`、是否未过期、是否匹配 `tool_name / operation / target / scope_hash`。
- 新写入审批记录包含 `prev_hash / event_hash`，可通过 `verify_approval_chain_tool` 校验账本完整性。
- 审计事件已有 `approval_requested / approval_partially_granted / approval_granted / approval_rejected / approval_renewed / approval_revoked / approval_expired / approval_cleanup / approval_policy_denied`。

当前短板：

- 审批账本已有本地哈希链和本地外部锚点；但还没有第三方透明日志、集中锚定或生产级锚点轮转。
- 本地 `approver` 仍只是字符串约束，不等价于生产级强身份认证；需要后续 B/S 或外部审批系统提供可信身份。

## 实施原则

- 保持向后兼容：旧的 `approvals.jsonl` 缺少新字段时仍能读取。
- 继续采用追加写账本：不原地修改旧记录，相同 `approval_id` 的最后一条有效记录代表当前状态。
- 审批不能放行 `critical` 风险，不能放行任意 shell。
- 审批增强先服务 MCP stdio 和本地账本；B/S 页面与外部 IAM/OA 暂不放入第一轮编码。
- 每个新增状态变更都要写审计事件，并能按 `trace_id` 回放。
- 测试优先覆盖“撤销后阻断、过期后阻断、续期后可继续、篡改账本可检测”。

## 目标链路

```text
request_* dry-run
-> data.approval_request
-> request_operation_approval_tool
-> record_operation_approval_tool
-> optional renew/revoke/cleanup
-> request_*(dry_run=false, approval_id=...)
-> approval_store.validate_approval()
-> ExecutionPolicy
-> fixed template
-> audit replay / approval ledger verification
```

## PR-A：审批生命周期增强

优先级最高，先补撤销、续期和过期清理。本节已在当前代码中完成，保留作为实现细节和回归对照。

### 代码改动

修改 `src/mcp_ops_server/approvals/store.py`：

- 扩展状态类型：

```python
ApprovalStatus = Literal[
    "requested",
    "granted",
    "rejected",
    "revoked",
    "expired",
]
```

- `ApprovalRecord` 增加兼容字段：

```python
schema_version: int = 2
updated_at: str | None = None
revoked_at: str | None = None
revoked_by: str | None = None
renewed_at: str | None = None
renewed_by: str | None = None
renewal_count: int = 0
last_action: str | None = None
```

- `from_dict()` 对旧记录默认补：
  - `schema_version=1`
  - `updated_at=created_at`
  - `renewal_count=0`
  - `last_action=status`
- 新增方法：

```python
def revoke_approval(
    self,
    *,
    approval_id: str,
    revoked_by: str,
    comment: str | None = None,
) -> ApprovalRecord:
    ...

def renew_approval(
    self,
    *,
    approval_id: str,
    renewed_by: str,
    expires_in_minutes: int,
    comment: str | None = None,
) -> ApprovalRecord:
    ...

def mark_expired_approvals(
    self,
    *,
    limit: int = 200,
    dry_run: bool = True,
) -> list[ApprovalRecord]:
    ...
```

- 状态流转规则：

| 当前状态 | 允许动作 | 新状态 |
| --- | --- | --- |
| `requested` | `grant` | `granted` |
| `requested` | `reject` | `rejected` |
| `requested` | `revoke` | `revoked` |
| `requested` | `expire` | `expired` |
| `granted` | `revoke` | `revoked` |
| `granted` | `renew` | `granted`，更新 `expires_at` 和 `renewal_count` |
| `granted` | `expire` | `expired` |
| `rejected` | 无 | 保持终态 |
| `revoked` | 无 | 保持终态 |
| `expired` | 无 | 保持终态 |

- `validate_approval()` 增强：
  - `revoked / expired / rejected / requested` 都必须阻断。
  - `expires_at <= now` 即使尚未被清理成 `expired`，也必须阻断。
  - 返回 `errors` 中明确包含 `approval revoked`、`approval expired` 等稳定字符串，方便测试断言。

修改 `src/mcp_ops_server/tool_groups/approval_tools.py`：

- 新增 MCP Tools：

```python
revoke_operation_approval_tool(
    approval_id: str,
    revoked_by: str,
    comment: str | None = None,
) -> dict

renew_operation_approval_tool(
    approval_id: str,
    renewed_by: str,
    expires_in_minutes: int = 60,
    comment: str | None = None,
) -> dict

cleanup_expired_operation_approvals_tool(
    limit: int = 200,
    dry_run: bool = True,
) -> dict
```

- 新增审计事件：
  - `approval_revoked`
  - `approval_renewed`
  - `approval_expired`
  - `approval_cleanup`
- 新增 `data.human_report`，继续复用 `_approval_report()`。

### 测试改动

扩展 `scripts/verify_mcp_operations.py`：

- `AP-004`：创建审批 -> grant -> revoke -> 再执行真实写操作，期望 `approval_validation.ok=false`，错误包含 `approval revoked`。
- `AP-005`：创建短 TTL 审批 -> 等待或直接构造过期记录 -> 执行真实写操作，期望 `approval expired`。
- `AP-006`：创建审批 -> grant -> renew -> 校验 `expires_at` 变大、`renewal_count=1`。
- `AP-007`：调用 `cleanup_expired_operation_approvals_tool(dry_run=true)` 不写账本，只返回候选。
- `AP-008`：调用 `cleanup_expired_operation_approvals_tool(dry_run=false)` 追加 `expired` 记录并写审计。

可选新增专项脚本：

```text
scripts/verify_approval_lifecycle.py
```

该脚本只依赖 `ApprovalStore`，用临时目录验证状态流转，不需要启动 MCP Server。

### 验收标准

- 已撤销审批不能进入真实执行。
- 已过期审批不能进入真实执行。
- 已拒绝审批不能被续期。
- 已撤销审批不能被重新 grant。
- 续期不改变 `tool_name / operation / target / scope_hash`。
- 清理过期审批默认 `dry_run=true`，不会误修改账本。

## PR-B：审批账本哈希链

第二优先级，补“审批账本自身可证明未被局部篡改”。本节已在当前代码中完成本地哈希链；后续锚点阶段也已补齐 HMAC 签名或外部锚点。

### 代码改动

已修改 `src/mcp_ops_server/approvals/store.py`：

- `ApprovalRecord` 增加：

```python
prev_hash: str | None = None
event_hash: str | None = None
```

- `_append()` 写入前：
  - 读取当前 `approvals.jsonl` 最后一条有效记录的 `event_hash`。
  - 第一条使用 `sha256:GENESIS`。
  - 对 payload 做稳定 JSON 序列化。
  - 计算 `event_hash = sha256(prev_hash + "\n" + canonical_payload)`。
- `from_dict()` 兼容旧记录缺少 hash 字段。

已新增文件：

```text
src/mcp_ops_server/approvals/verifier.py
scripts/verify_approval_chain.py
```

`verify_approval_chain.py` 验证：

- 原始账本通过。
- 修改中间记录失败。
- 删除中间记录失败。
- 旧格式无链字段记录失败。

已修改 `src/mcp_ops_server/tool_groups/approval_tools.py`：

- 新增只读工具：

```python
verify_approval_chain_tool(
    approval_file: str | None = None,
) -> dict
```

### 验收标准

- 新写入的审批记录都有 `prev_hash / event_hash`。
- 老账本仍可读取，但验证工具要明确提示旧记录缺少 hash。
- 篡改任意一行会被定位到行号。

后续增强：

- 增加 `TMP_MCP_APPROVAL_CHAIN_SECRET` 可选 HMAC-SHA256 签名。
- 或复用审计锚点模式，为审批账本创建外部锚点，避免本地账本被整体重算后仍看似完整。

## PR-C：审批策略配置与多级审批

第三优先级，先做可配置策略，再做最小多级审批。

详细编码入口见 `PR_C_APPROVAL_POLICY_DEV_PLAN.md`。该独立文档已经细化配置文件、策略加载器、`partially_granted` 状态、审批人历史、AstrBot 工具暴露边界和新增验证脚本。

### 新增配置

新增：

```text
config/approvals/policies.yaml
config/approvals/README.md
src/mcp_ops_server/approvals/policy.py
```

`policies.yaml` 示例：

```yaml
version: "1.0.0"
default:
  ttl_minutes: 60
  max_renewals: 1
  required_approvals: 1
  require_distinct_approvers: true
rules:
  - id: CRITICAL_DENY
    match:
      risk_level: critical
    decision: deny
    reason: "critical 风险不能通过审批放行"
  - id: SYSTEM_PATH_TWO_APPROVERS
    match:
      path_prefix:
        - "/etc"
        - "C:\\Windows"
    ttl_minutes: 30
    required_approvals: 2
  - id: NETWORK_CHANGE_SHORT_TTL
    match:
      operation: network_policy_change
    ttl_minutes: 30
    required_approvals: 1
```

### 代码改动

新增 `ApprovalPolicyDecision`：

```python
@dataclass(frozen=True)
class ApprovalPolicyDecision:
    decision: Literal["allow_request", "deny_request"]
    ttl_minutes: int
    required_approvals: int
    max_renewals: int
    require_distinct_approvers: bool
    matched_rule_ids: list[str]
    reasons: list[str]
```

接入点：

- `ApprovalStore.request_approval()` 创建审批时加载策略：
  - `critical` 直接拒绝创建审批。
  - 限制 `expires_in_minutes <= policy.ttl_minutes`。
  - 写入 `required_approvals / policy_rule_ids`。
- `record_decision()`：
  - 多级审批下，单个 `grant` 不一定让状态变 `granted`。
  - 新增字段 `approver_history`，记录每个审批人和时间。
  - 当有效 grant 数达到 `required_approvals` 后才变 `granted`。
  - `require_distinct_approvers=true` 时，同一 approver 重复 grant 不计数。

状态建议扩展：

```python
ApprovalStatus = Literal[
    "requested",
    "partially_granted",
    "granted",
    "rejected",
    "revoked",
    "expired",
]
```

### 工具改动

- `request_operation_approval_tool` 返回：
  - `data.approval.required_approvals`
  - `data.approval.policy_rule_ids`
  - `data.approval.policy_reasons`
- `record_operation_approval_tool` 在未达到多级审批人数时：
  - `ok=true`
  - `status=partially_granted`
  - `next_actions` 提示还差几个审批人。
- `list_operation_approvals_tool` 支持按 `status=partially_granted` 过滤。

### 验收标准

- `required_approvals=2` 时，一个 approver grant 后不能进入真实执行。
- 第二个不同 approver grant 后才能进入真实执行。
- 同一 approver 重复 grant 不能凑数。
- `critical` 风险不能创建审批申请。
- TTL 被策略压缩后，返回中能看到最终 `expires_at` 和匹配规则。

## PR-D：B/S 与外部审批预留

本轮先预留边界，不建议直接做页面。当前已完成 PR-D 预开发第一步：外部审批身份 token 校验。

可先在代码中保持这些接口形态：

- `requester`
- `approver`
- `operator`
- `trace_id`
- `session_id`
- `policy_rule_ids`
- `approval_id`
- `scope_hash`

后续 B/S 管理端应只调用 MCP 工具或未来 HTTP API，不直接写 `approvals.jsonl`。

外部审批系统接入点建议放在：

```text
src/mcp_ops_server/approvals/external.py
```

当前第一版已经提供：

```python
class ExternalApprovalClient(Protocol):
    def submit_request(self, record: ApprovalRecord) -> dict[str, Any]:
        ...

    def fetch_decision(self, approval_id: str) -> dict[str, Any]:
        ...
```

同时新增 HMAC-SHA256 审批决策 token 校验：

- `record_operation_approval_tool` 新增 `approval_token` 参数。
- `TMP_MCP_REQUIRE_APPROVAL_IDENTITY=true` 时，缺失或无效 token 不会写入审批账本。
- token 通过后，身份摘要写入 `approver_history[].identity`。
- 审计事件新增 `approval_identity_denied` 和 `approval_identity_verified`。
- 专项验证脚本为 `scripts/verify_approval_identity.py`。

## 文件级任务清单

当前已完成 1-16，并已补齐 B/S 审批控制台 bundle、企业身份断言签发 token、托管式 B/S 网关和网关选项控制台；后续建议继续推进真实企业身份/KMS 接入和受限执行代理：

1. `src/mcp_ops_server/approvals/store.py`
   - 扩状态、扩字段、补状态流转、补撤销/续期/过期清理方法。
2. `src/mcp_ops_server/tool_groups/approval_tools.py`
   - 新增 revoke/renew/cleanup 工具和 human report。
3. `scripts/verify_approval_lifecycle.py`
   - 新增专项脚本，先独立验证生命周期。
4. `scripts/verify_mcp_operations.py`
   - 将生命周期用例接入全量验收。
5. `src/mcp_ops_server/approvals/verifier.py`
   - 实现审批账本哈希链校验。
6. `scripts/verify_approval_chain.py`
   - 验证篡改检测。
7. `config/approvals/policies.yaml`
   - 加默认策略和示例策略。
8. `src/mcp_ops_server/approvals/policy.py`
   - 接入策略加载、匹配和多级审批。
9. `docs/testing/MCP_OPERATION_VERIFICATION.md`
   - 补 AP-004 到 AP-008 与多级审批验收说明。
10. `docs/user/USAGE.md`
   - 补 AstrBot 手工提示词。
11. `docs/history/CHANGELOG.md`
   - 记录实现版本和验证结果。

已完成的后续增强：

12. `src/mcp_ops_server/approvals/anchor.py`
   - 为审批账本增加外部锚点和可选 HMAC 签名。
13. `tool_groups/approval_tools.py`
   - 已暴露 `anchor_approval_chain_tool` 和 `verify_approval_anchor_tool`。

后续建议新增：

14. `docs/architecture/PR_D_APPROVAL_UI_AND_IDENTITY_PREDEV.md`
   - 已新增，记录 B/S 审批页面、外部审批服务和可信身份通道预开发边界。
15. `src/mcp_ops_server/approvals/external.py`
   - 已新增，定义外部审批接口、HMAC token 创建和验证逻辑。
16. `scripts/verify_approval_identity.py`
   - 已新增，验证缺失 token、签名 token、错误审批人、错误 scope、篡改 token 和哈希链兼容。

## 自动化命令

完成 PR-A 后至少运行：

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe -m compileall -q tmp_MCP\src\mcp_ops_server tmp_MCP\scripts
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_lifecycle.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_chain.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_policy.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_anchor.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_identity.py
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_mcp_operations.py
```

完成 PR-B 后额外运行：

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_chain.py
```

完成审批锚点后额外运行：

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_anchor.py
```

完成 PR-D 身份 token 后额外运行：

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe tmp_MCP\scripts\verify_approval_identity.py
```

## AstrBot 手工验收提示词

撤销审批：

```text
只允许通过 MCP 工具调用，不要使用 shell。先调用 request_modify_file 生成 dry_run 计划，再创建审批申请并记录 grant，然后调用 revoke_operation_approval_tool 撤销该 approval_id。最后尝试用该 approval_id 执行 dry_run=false，说明为什么被 approval_validation 阻断。
```

续期审批：

```text
只允许通过 MCP 工具调用，不要使用 shell。创建一个 request_modify_file 的审批申请并记录 grant，然后调用 renew_operation_approval_tool 延长 30 分钟，说明新的 expires_at、renewal_count 和 scope_hash 是否变化。
```

审批账本校验：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 verify_approval_chain_tool 校验审批账本，并说明 checked_records、first_bad_line、expected_hash 和 actual_hash。
```

审批账本锚点：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 anchor_approval_chain_tool 为当前审批账本创建外部锚点，再调用 verify_approval_anchor_tool 校验，并说明 head_hash、anchored_head_hash、file_sha256、signature_ok 和 errors。
```

多级审批：

```text
只允许通过 MCP 工具调用，不要使用 shell。创建一个命中多级审批策略的网络策略变更审批申请，先由 approver-a grant，说明为什么仍是 partially_granted；再由 approver-b grant，说明为什么变为 granted。
```

## 非目标

- 不做任意命令执行。
- 不做独立托管的 B/S 网关、正式登录态或企业 IAM/OA 接入。
- 不直接接企业 IAM/OA。
- 不把审批通过视为绕过 `ExecutionPolicy` 的通行证。
- 不放开需要提权的服务、防火墙、包管理、权限模板。

## 完成后的预期

审批增强完成后，整条链路应具备：

- 审批可以撤销。
- 审批可以按策略续期。
- 过期审批可以显式清理和审计。
- 审批账本可以校验篡改。
- 审批账本可以通过外部锚点或 HMAC 签名降低整体重算风险。
- 不同风险、工具、路径可以使用不同审批策略。
- 多级审批能阻止单人误批高风险变更。
- `approval_validation` 与 `execution_validation` 继续保持分层：审批解决“谁允许”，执行策略解决“系统实际能否安全执行”。
