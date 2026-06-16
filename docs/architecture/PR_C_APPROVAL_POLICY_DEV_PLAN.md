# PR-C 审批策略配置与多级审批开发文档

本文档是 PR-C 代码开发的执行版说明与实现记录，承接：

- `APPROVAL_ENHANCEMENT_IMPLEMENTATION_PLAN.md`
- `V0_5_ALPHA_APPROVAL_ROADMAP.md`
- 当前已完成的 PR-A 审批生命周期增强
- 当前已完成的 PR-B 审批账本哈希链

目标不是把审批变成同一个 Agent 的自动自批，而是把现有“审批结果可信、审批账本可校验”继续推进为“审批决策受策略约束、多人审批可验证、普通会话不能自批”。

## 当前状态

截至 2026-06-10，PR-C 已落地：

- `config/approvals/policies.yaml` 和 `config/approvals/README.md`。
- `src/mcp_ops_server/approvals/policy.py` 策略加载、匹配和审批人校验。
- `ApprovalRecord` schema v3 策略字段、`partially_granted` 状态和 `approver_history`。
- `approval_policy_denied`、`approval_partially_granted`、`approval_granted` 等审计事件。
- `scripts/verify_approval_policy.py`，当前 32 / 32 PASS。
- `scripts/verify_mcp_operations.py` 中 `approval_policy` 全链路用例已接入全量验收；后续阶段当前全量目标为 60 / 60 PASS。
- 审批账本外部锚点/HMAC 已在后续阶段落地：`approvals/anchor.py`、`anchor_approval_chain_tool`、`verify_approval_anchor_tool` 和 `scripts/verify_approval_anchor.py`。
- PR-D 外部审批身份通道预开发已在后续阶段落地：`approvals/external.py`、`record_operation_approval_tool(approval_token=...)` 和 `scripts/verify_approval_identity.py`。
- B/S 审批审核包、审批控制台 bundle 和企业身份断言签发 token 已在后续阶段落地：`get_approval_review_packet_tool`、`get_approval_console_bundle_tool`、`issue_enterprise_approval_token_tool` 和 `scripts/verify_approval_console.py`。
- 托管式 B/S 审批/配置网关和网关选项控制台已在后续阶段落地：`web/gateway.py`、`web_gateway.py`、`web/gateway_settings.py`、`config/web_gateway.py` 和 `scripts/verify_web_gateway.py`。

下一步不再重复 PR-C、审批锚点、PR-D token 预开发、控制台 bundle 或托管式网关 MVP，应继续推进真实企业身份/OIDC/KMS 接入、服务端会话、CSRF、防重放、密钥轮转/撤销或真实受限执行代理。

## 目标

PR-C 要完成三件事：

1. 增加审批策略配置，按风险等级、工具、操作、目标路径或目标服务决定 TTL、审批人数和是否允许创建审批。
2. 增加最小多级审批能力，一个审批可以经历 `requested -> partially_granted -> granted`。
3. 明确 AstrBot 集成边界，普通用户会话只能申请和查询审批，审批人通道才能记录 `grant / reject / revoke / renew`。

## 非目标

本阶段不做：

- B/S 审批页面。
- 外部 IAM、OAuth、LDAP、企业微信或飞书审批流。
- 任意 shell 执行。
- 放开 `critical` 风险审批。
- 真实 sudoers/JEA 部署。
- 审批账本 HMAC 或外部锚点。

这些能力分别进入后续 PR-D、执行代理和账本外部锚点阶段。

## 当前基线

当前已具备：

- `validate_operation_intent_tool` 会把 `rm -rf`、`sudo rm -rf`、危险权限、下载后执行和提示词注入判为 `critical` 并拒绝。
- `request_*` 写操作工具在 `dry_run=true` 时生成 `approval_request` 和 `execute_after_approval`。
- `request_operation_approval_tool` 创建本地 JSONL 审批记录。
- `record_operation_approval_tool` 记录 `grant / reject`。
- `renew_operation_approval_tool`、`revoke_operation_approval_tool`、`cleanup_expired_operation_approvals_tool` 处理生命周期。
- `verify_approval_chain_tool` 校验审批账本 `prev_hash / event_hash` 哈希链。
- 真实执行前会校验 `approval_id`、状态、过期时间、`tool_name / operation / target / scope_hash`。
- `ExecutionPolicy` 会继续阻断未部署受限身份的提权模板。

当前缺口：

- 没有策略文件，不同工具、路径和风险等级不能配置不同审批规则。
- 没有 `partially_granted` 状态。
- 没有 `required_approvals`、审批进度和审批人历史。
- 如果 AstrBot 把 `record_operation_approval_tool` 暴露给普通会话，同一个 Agent 可能模拟自批。
- `approver` 目前只是字符串，不等于真实身份认证。

## 目标链路

### high 风险固定模板

```text
request_* dry_run=true
  -> guardrail 允许生成计划
  -> 返回 approval_request
  -> request_operation_approval_tool 加载策略
  -> 创建 requested 审批
  -> 审批人 A grant
  -> 若 required_approvals > 1，则状态 partially_granted
  -> 审批人 B grant
  -> 达到 required_approvals 后状态 granted
  -> request_* dry_run=false + approval_id
  -> ApprovalStore.validate_approval()
  -> ExecutionPolicy.validate()
  -> 固定模板执行或被执行策略阻断
```

### critical 风险

```text
critical 输入
  -> guardrail decision=deny
  -> request_operation_approval_tool 即使被手工调用也应拒绝
  -> 不产生可执行的 granted approval_id
```

## 新增文件

```text
config/approvals/README.md
config/approvals/policies.yaml
src/mcp_ops_server/approvals/policy.py
scripts/verify_approval_policy.py
```

## 配置文件

默认路径：

```text
config/approvals/policies.yaml
```

环境变量覆盖：

```text
TMP_MCP_APPROVAL_POLICY_FILE
```

建议第一版配置：

```yaml
version: "1.0.0"

default:
  decision: allow_request
  ttl_minutes: 60
  max_renewals: 1
  required_approvals: 1
  require_distinct_approvers: true
  allow_self_approval: false

approvers:
  trusted_ids:
    - verify-admin
    - approver-a
    - approver-b
  roles:
    ops_admin:
      - verify-admin
    network_admin:
      - approver-a
      - approver-b

rules:
  - id: CRITICAL_DENY
    match:
      risk_level: critical
    decision: deny_request
    reason: "critical 风险不能通过审批放行"

  - id: NETWORK_CHANGE_TWO_APPROVERS
    match:
      operation: network_policy_change
    ttl_minutes: 30
    required_approvals: 2
    approver_roles:
      - network_admin
    reason: "网络策略变更需要两名网络审批人"

  - id: SYSTEM_PATH_TWO_APPROVERS
    match:
      path_prefix:
        - "/etc"
        - "C:\\Windows"
    ttl_minutes: 30
    required_approvals: 2
    approver_roles:
      - ops_admin
    reason: "系统路径变更需要双人审批"

  - id: TEMP_FILE_SINGLE_APPROVER
    match:
      operation: modify_file
      path_prefix:
        - "%TEMP%"
        - "/tmp"
    ttl_minutes: 45
    required_approvals: 1
    reason: "临时文件修改保留单人审批"
```

实现时先支持这些匹配字段：

- `risk_level`
- `tool_name`
- `operation`
- `target`
- `path_prefix`

匹配规则：

- `rules` 从上到下匹配，允许多条命中。
- `decision=deny_request` 的规则优先级最高。
- `ttl_minutes` 取命中规则中的最小值。
- `required_approvals` 取命中规则中的最大值。
- `max_renewals` 取命中规则中的最小值。
- `approver_roles` 合并去重。
- 没有命中规则时使用 `default`。

## policy.py 接口

新增：

```python
@dataclass(frozen=True)
class ApprovalPolicyDecision:
    decision: Literal["allow_request", "deny_request"]
    ttl_minutes: int
    required_approvals: int
    max_renewals: int
    require_distinct_approvers: bool
    allow_self_approval: bool
    trusted_approver_ids: tuple[str, ...]
    allowed_approver_roles: tuple[str, ...]
    allowed_approver_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    source_path: str
    loaded_from_config: bool
    errors: tuple[str, ...] = ()
```

建议函数：

```python
def default_policy_path() -> Path: ...
def clear_policy_cache() -> None: ...
def load_approval_policy(path_text: str | None = None) -> ApprovalPolicySet: ...
def evaluate_approval_policy(
    *,
    tool_name: str,
    operation: str,
    target: str,
    risk_level: str,
    params: dict[str, Any],
) -> ApprovalPolicyDecision: ...
def validate_approver(
    *,
    decision: ApprovalPolicyDecision,
    approver: str,
    requester: str | None,
    existing_approvers: set[str],
) -> tuple[bool, list[str]]: ...
```

加载方式参考 `guardrails/rule_loader.py`：

- 优先使用 PyYAML。
- PyYAML 不存在时可尝试 JSON。
- 配置加载失败时回退安全默认值。
- 回退默认值必须保持 `critical -> deny_request`。

## ApprovalRecord 字段扩展

建议把新写入记录升级为 `schema_version=3`。

新增字段：

```python
required_approvals: int = 1
granted_approvals: int = 0
require_distinct_approvers: bool = True
allow_self_approval: bool = False
max_renewals: int = 1
policy_rule_ids: tuple[str, ...] = ()
policy_reasons: tuple[str, ...] = ()
allowed_approver_roles: tuple[str, ...] = ()
allowed_approver_ids: tuple[str, ...] = ()
approver_history: tuple[dict[str, Any], ...] = ()
```

`approver_history` 单项建议：

```json
{
  "approver": "approver-a",
  "decision": "grant",
  "recorded_at": "2026-06-10T10:00:00Z",
  "comment": "同意本次变更",
  "policy_rule_ids": ["NETWORK_CHANGE_TWO_APPROVERS"]
}
```

兼容策略：

- 读取旧 `schema_version=1/2` 记录时，缺省 `required_approvals=1`。
- 旧 `granted` 记录继续有效。
- 新写入记录带新字段，并继续进入审批账本哈希链。
- 不回写历史记录。

## 状态机

扩展：

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

状态规则：

| 当前状态 | 动作 | 结果 |
| --- | --- | --- |
| `requested` | 第 1 个有效 grant，未达到人数 | `partially_granted` |
| `requested` | grant 后达到人数 | `granted` |
| `partially_granted` | 新的有效 grant，仍未达到人数 | `partially_granted` |
| `partially_granted` | 新的有效 grant，达到人数 | `granted` |
| `requested / partially_granted` | reject | `rejected` |
| `requested / partially_granted / granted` | revoke | `revoked` |
| `requested / partially_granted / granted` | 过期清理 | `expired` |

重复审批人：

- `require_distinct_approvers=true` 时，同一 `approver` 重复 grant 不计数。
- 第一版建议直接返回 `ok=false`，错误为 `duplicate approver`，不追加审批记录。
- 后续如果需要审计重复尝试，可只写审计事件，不写审批账本状态。

自审批：

- `allow_self_approval=false` 且 `approver == requester` 时返回 `ok=false`。
- 注意：这不是强身份认证，只是本地策略约束。生产仍需要 AstrBot 工具暴露边界或外部审批系统。

## Store 改造点

文件：

```text
src/mcp_ops_server/approvals/store.py
```

`request_approval()`：

- 调用 `evaluate_approval_policy()`。
- 若 `decision=deny_request`，抛出稳定错误，例如 `approval request denied by policy`。
- `critical` 风险必须拒绝创建审批。
- `expires_in_minutes` 不能超过策略 TTL。
- 写入 `required_approvals / policy_rule_ids / policy_reasons / max_renewals`。

`record_decision()`：

- 允许当前状态为 `requested` 或 `partially_granted`。
- `reject` 直接进入 `rejected`。
- `grant` 前校验：
  - 审批未过期。
  - 审批未终止。
  - `approver` 可信或匹配策略允许列表。
  - 不能自批，除非策略允许。
  - 重复审批人不能计数。
- 追加 `approver_history`。
- 根据有效 grant 数决定 `partially_granted` 或 `granted`。

`renew_approval()`：

- 仍只允许 `granted` 且未过期的审批续期。
- `renewal_count >= max_renewals` 时拒绝，错误为 `max renewals exceeded`。
- 续期分钟数不能超过策略 TTL。

`validate_approval()`：

- 只有 `status=granted` 才通过。
- `partially_granted` 返回错误 `approval not fully granted`。
- 其他错误保持稳定字符串。

`list_recent()`：

- 支持 `status=partially_granted` 过滤。

## MCP 工具改造点

文件：

```text
src/mcp_ops_server/tool_groups/approval_tools.py
```

`request_operation_approval_tool` 返回新增字段：

```text
data.approval.required_approvals
data.approval.granted_approvals
data.approval.policy_rule_ids
data.approval.policy_reasons
data.approval.max_renewals
```

策略拒绝时：

- `ok=false`
- `risk_level` 使用请求风险
- `summary="审批申请被策略拒绝。"`
- `data.error` 包含稳定错误
- 写入 `approval_policy_denied` 审计事件

`record_operation_approval_tool`：

- `partially_granted` 时 `ok=true`。
- `summary` 要说明还差几个审批人。
- `next_actions` 提示继续由不同审批人 grant。
- 事件类型：
  - `approval_partially_granted`
  - `approval_granted`
  - `approval_rejected`

`get_operation_approval_tool` 和 `list_operation_approvals_tool`：

- human report evidence 增加：
  - `required_approvals`
  - `granted_approvals`
  - `policy_rule_ids`

## AstrBot 工具暴露边界

PR-C 必须在文档和配置建议中明确：

普通用户会话建议暴露：

```text
request_operation_approval_tool
get_operation_approval_tool
list_operation_approvals_tool
verify_approval_chain_tool
```

审批人或管理员通道才暴露：

```text
record_operation_approval_tool
renew_operation_approval_tool
revoke_operation_approval_tool
cleanup_expired_operation_approvals_tool
```

原因：

- MCP 工具可以记录审批事实，但不能凭空证明 `approver` 字符串就是本人。
- 如果同一个普通 Agent 同时拥有申请和 grant 工具，它可能在提示词诱导下完成自批。
- PR-C 的本地策略能阻止明显自批和重复审批人，但生产级身份可信仍需要后续 B/S 或外部审批系统。

## 测试脚本

新增：

```text
scripts/verify_approval_policy.py
```

建议覆盖：

1. 默认策略加载成功。
2. 临时文件修改命中单人审批。
3. 网络策略变更命中双人审批。
4. `critical` 风险创建审批被策略拒绝。
5. 第一名审批人 grant 后状态为 `partially_granted`。
6. `partially_granted` 不能进入真实执行，错误包含 `approval not fully granted`。
7. 同一审批人重复 grant 被拒绝，错误包含 `duplicate approver`。
8. 第二名不同审批人 grant 后状态为 `granted`。
9. 达到 `granted` 后 `validate_approval()` 通过。
10. 自批被拒绝，错误包含 `self approval denied`。
11. TTL 被策略压缩。
12. 超过 `max_renewals` 的续期被拒绝。
13. 新字段进入审批账本哈希链，`verify_approval_chain()` 通过。

全量脚本：

```text
scripts/verify_mcp_operations.py
```

新增用例：

- `approval_policy_denies_critical_request`
- `approval_multi_step_blocks_partial`
- `approval_multi_step_allows_after_second_grant`
- `approval_duplicate_approver_blocked`
- `approval_self_approval_blocked`

## 验收命令

在 `tmp_MCP` 目录运行：

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_MCP\src"
D:\miniconda\envs\astrbot\python.exe -m compileall -q src\mcp_ops_server scripts
D:\miniconda\envs\astrbot\python.exe scripts\verify_approval_lifecycle.py
D:\miniconda\envs\astrbot\python.exe scripts\verify_approval_chain.py
D:\miniconda\envs\astrbot\python.exe scripts\verify_approval_policy.py
D:\miniconda\envs\astrbot\python.exe scripts\verify_mcp_operations.py
```

预期：

- 生命周期脚本继续全绿。
- 哈希链脚本继续全绿。
- 新增策略脚本全绿。
- 全量 MCP 验收新增多级审批用例后仍 `passed = total`。

## AstrBot 手工验证提示词

### 策略拒绝 critical

```text
只允许通过 MCP 工具调用，不要使用 shell。
调用 validate_operation_intent_tool 检查 command="sudo rm -rf /"。
然后说明为什么该请求是 critical、decision=deny，并且不能进入 request_operation_approval_tool 审批放行。
```

### 双人审批

```text
只允许通过 MCP 工具调用，不要使用 shell。
创建一个命中双人审批策略的网络策略变更 dry-run 计划，不要真实修改防火墙。
复制 data.approval_request 调用 request_operation_approval_tool 创建审批。
然后由 approver-a 调用 record_operation_approval_tool grant。
请说明为什么当前仍是 partially_granted，以及还差几个审批人。
```

### 部分审批不能真实执行

```text
只允许通过 MCP 工具调用，不要使用 shell。
复用上一步 partially_granted 的 approval_id，尝试按 execute_after_approval 参数发起 dry_run=false。
不要使用 shell。请说明 approval_validation 为什么阻断，以及错误是否包含 approval not fully granted。
```

### 第二人审批后再校验

```text
只允许通过 MCP 工具调用，不要使用 shell。
由 approver-b 对同一个 approval_id 调用 record_operation_approval_tool grant。
随后调用 get_operation_approval_tool 查询状态。
请说明 status、required_approvals、granted_approvals、approver_history 和 policy_rule_ids。
```

### 账本仍可信

```text
只允许通过 MCP 工具调用，不要使用 shell。
调用 verify_approval_chain_tool 校验审批账本。
请说明 ok、checked_records、first_bad_line、expected_hash 和 actual_hash。
```

## 实现顺序

建议按这个顺序提交代码：

1. 增加 `config/approvals/policies.yaml` 和 README。
2. 新增 `approvals/policy.py`，先写纯函数和加载器。
3. 新增 `scripts/verify_approval_policy.py` 的策略加载与匹配测试。
4. 扩展 `ApprovalRecord` 字段和 `ApprovalStatus`。
5. 改造 `request_approval()`，接入策略拒绝、TTL 压缩和策略字段落账。
6. 改造 `record_decision()`，实现 `partially_granted`、重复审批人、自批拦截。
7. 改造 `validate_approval()`，阻断 `partially_granted`。
8. 改造 `renew_approval()`，支持 `max_renewals`。
9. 改造 `approval_tools.py` 的返回、human report 和审计事件。
10. 把策略用例接入 `verify_mcp_operations.py`。
11. 更新 `USAGE.md`、`MCP_OPERATION_VERIFICATION.md`、`DEVELOPMENT.md`、`TODO.md` 和 `CHANGELOG.md`。

## 完成定义

PR-C 完成时必须满足：

- `critical` 风险无法创建可执行审批。
- 策略文件缺失或损坏时，系统回退到安全默认策略。
- 双人审批规则下，一个审批人 grant 不会变成 `granted`。
- `partially_granted` 的 `approval_id` 不能进入真实执行。
- 同一审批人不能重复凑数。
- 默认不允许 `requester` 自批。
- `required_approvals / granted_approvals / approver_history / policy_rule_ids` 出现在工具返回和 human report 里。
- 新审批记录仍通过审批账本哈希链校验。
- 全量验证脚本通过。

## 关键风险

- 本地 `approver` 字符串不是强身份认证。PR-C 只能降低误用风险，不能替代 B/S 或外部 IAM。
- 如果 AstrBot 普通会话暴露 `record_operation_approval_tool`，仍可能被提示词诱导去模拟审批人。
- 多级审批会增加状态流转复杂度，必须保持错误字符串稳定，避免 AstrBot 难以解释。
- 新字段必须进入 `to_dict()`，否则哈希链和查询结果会不一致。

## 后续衔接

PR-C、审批锚点、托管式 B/S 网关和网关选项控制台完成后，下一步建议：

1. 接入真实企业身份系统和生产级网关会话，让 `approver` 来自真实登录态、外部审批服务、OIDC/IAM 或 KMS 签名通道，并补齐 CSRF、防重放和 token 撤销。
2. 继续落地 Linux/麒麟受限 `ops-agent`、sudoers allowlist 和 Windows JEA。
3. 为审计与审批锚点增加轮转、集中查询和第三方透明日志上传。
