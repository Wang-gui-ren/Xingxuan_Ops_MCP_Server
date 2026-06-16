# 护栏审计链路增强路线图

本文档用于规划 `0.3.0-alpha` 的最高优先级开发：规则配置化、审计日志防篡改、`trace_id` 自动生成与链路串联。它承接当前 `0.2.0-alpha` 已完成的内置规则、JSONL 审计和写工具接入工作，目标是让项目在比赛答辩中能展示“可维护规则库、可验证审计链、可回放执行链路”。

## 开发目标

下一阶段要解决三个问题：

- 规则现在写在 `guardrails/patterns.py` 中，能运行但不利于现场展示、规则版本管理和测试样例沉淀。
- 审计日志现在是普通 JSONL，能回放但还不能证明日志未被篡改。
- `trace_id` 和 `session_id` 已有字段，但依赖调用方传入，无法稳定串起一次对话中的安全校验、工具结果和审计查询。

目标完成后，项目应支持：

- `config/guardrails/rules.yaml` 作为可展示、可版本化、可测试的规则库。
- `audit/logger.py` 追加 `prev_hash` 与 `event_hash`，形成单文件 JSONL 哈希链。
- 工具入口自动补齐 `trace_id`，并在 `guardrail_decision -> tool_result -> audit_query` 中持续透传。
- 自动化测试能证明规则启停、哈希链校验、篡改检测和 trace 查询有效。

## 优先级排序

| 优先级 | 能力 | 原因 |
| --- | --- | --- |
| P0 | 规则配置化 | 比赛展示价值最高，能把“写死正则”升级为“安全策略规则库” |
| P0 | 审计日志防篡改 | 直接贴合赛题“可追溯审计”和异常回溯要求 |
| P0 | trace 链路串联 | 让审计从“多条日志”升级为“完整事件时间线” |
| P1 | 规则热加载 | 适合演示现场追加规则，但要在基础校验稳定后再做 |
| P1 | 外部锚点与签名 | 已补本地 `anchors.jsonl` 和可选 HMAC；第三方透明日志后续增强 |

## 规则配置化设计

### 目标文件

建议新增：

```text
tmp_MCP/config/guardrails/
├─ rules.yaml          # 默认规则库
└─ README.md           # 规则维护说明
```

建议新增代码：

```text
tmp_MCP/src/mcp_ops_server/guardrails/
├─ rule_loader.py      # 加载、校验、编译规则
├─ rule_schema.py      # RuleDefinition、RuleTestCase 等模型
└─ patterns.py         # 暂时保留为兼容 fallback
```

### 规则字段

每条规则必须包含：

```yaml
- id: CMD_RM_RF
  category: destructive_command
  risk_level: critical
  pattern: "(^|[\\r\\n;&|]\\s*)(sudo\\s+)?rm\\s+(--\\s+)?(-[^\\s]*[rR][fF][^\\s]*|-[^\\s]*[fF][rR][^\\s]*)(\\s|$)"
  enabled: true
  version: "1.0.0"
  source: "tmp_MCP built-in; inspired by OWASP MCP/LLM safety guidance"
  recommendation: "改用 find_large_files_tool 定位文件，再用 request_log_cleanup 生成 dry-run 计划。"
  test_cases:
    - input: "rm -rf /"
      expect_match: true
      expect_risk_level: critical
      expect_decision: deny
    - input: "rm -i ./single.log"
      expect_match: false
```

推荐扩展字段：

```yaml
  description: "检测 Linux 递归强制删除命令。"
  match_targets: ["command", "user_intent", "params"]
  flags: ["ignore_case"]
  created_at: "2026-06-03"
  updated_at: "2026-06-03"
  false_positive_notes: "仅匹配 -rf/-fr 组合，不匹配 rm -i。"
```

### 规则分类

第一批迁移当前 `patterns.py` 中已有类别：

| category | 说明 |
| --- | --- |
| `prompt_injection` | 忽略规则、跳过审计、角色扮演越权 |
| `destructive_command` | 删除、格式化、覆盖写入、批量清空 |
| `permission_escalation` | 危险 chmod/chown、权限扩大 |
| `network_exfiltration` | 下载后执行、编码执行、动态执行 |
| `service_disruption` | 禁用安全服务、阻断远程管理端口 |
| `scope_expansion` | 通配符、递归、路径穿越、范围不明确 |
| `protected_path` | 系统路径、数据库路径、容器路径、审计路径 |
| `tool_risk` | MCP 写工具默认风险 |
| `external_guard` | 璇玑 Guardrail 等上游护栏摘要 |

### 加载策略

建议 `rule_loader.py` 的加载顺序：

```text
读取 TMP_MCP_GUARDRAIL_RULES_FILE
-> 未配置则读取 tmp_MCP/config/guardrails/rules.yaml
-> 文件不存在或格式错误时回退到 patterns.py 内置规则
-> 编译正则
-> 校验 test_cases
-> 返回 enabled=true 的规则
```

第一版不要做热加载。MCP Server 启动时加载一次即可，避免运行中规则半更新导致行为不确定。

### 兼容策略

迁移不能一次性删除 `patterns.py`。建议分三步：

- 第一阶段：新增 YAML 和 loader，`risk_engine.py` 优先使用 YAML，失败时 fallback 到 `patterns.py`。
- 第二阶段：自动化测试覆盖 YAML 中所有 `test_cases`，并验证 YAML 与旧规则行为一致。
- 第三阶段：`patterns.py` 只保留最小 fallback，主规则完全迁移到 `rules.yaml`。

### 验收用例

必须新增自动化测试：

- `rules.yaml` 能成功加载并编译所有 enabled 规则。
- 每条规则的 `test_cases` 都能通过。
- 将 `CMD_RM_RF.enabled=false` 后，`rm -rf /` 不再由该规则命中，但仍可能被其他保护路径规则拦截。
- 错误正则不会导致 MCP Server 崩溃，应返回明确加载错误并回退。
- `source`、`version`、`recommendation` 能进入 `GuardrailFinding`，便于答辩展示。

## 审计日志防篡改设计

### 哈希链字段

建议在每条审计事件落盘时追加：

```json
{
  "prev_hash": "sha256:...",
  "event_hash": "sha256:..."
}
```

含义：

- `prev_hash`：同一个审计文件中上一条事件的 `event_hash`。
- `event_hash`：当前事件规范化 JSON 与 `prev_hash` 拼接后的 SHA-256。
- 第一条事件的 `prev_hash` 固定为 `sha256:GENESIS`。

### 规范化哈希输入

哈希必须基于稳定序列化结果，避免字段顺序不同导致校验失败。

建议算法：

```text
payload = sanitize_payload(event.to_dict())
payload_without_hash = remove(payload, ["prev_hash", "event_hash"])
canonical = json.dumps(payload_without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
event_hash = "sha256:" + sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()
```

注意：

- 先脱敏再哈希，保证落盘内容与哈希内容一致。
- `event_hash` 不参与自身哈希。
- `prev_hash` 必须参与当前哈希。
- 不建议第一版跨文件串链，按天文件内成链即可。

### 校验工具

建议新增：

```text
tmp_MCP/src/mcp_ops_server/audit/verifier.py
tmp_MCP/scripts/verify_audit_chain.py
```

并可选暴露 MCP 只读工具：

```text
verify_audit_chain_tool
```

返回结构：

```json
{
  "ok": false,
  "summary": "审计哈希链校验失败：第 17 行 event_hash 不匹配。",
  "data": {
    "file": "audit-20260603.jsonl",
    "checked_events": 17,
    "first_bad_line": 17,
    "expected_hash": "sha256:...",
    "actual_hash": "sha256:..."
  }
}
```

### 篡改检测边界

本地哈希链能证明：

- 中间任意一行被改动会导致该行及后续链路校验失败。
- 删除中间行会导致后续 `prev_hash` 不匹配。
- 插入伪造行需要重算后续所有行哈希，能被外部锚点进一步发现。

本地哈希链不能单独证明：

- 攻击者重写整个文件并重算所有哈希。
- 攻击者删除最后几行并声称从未发生。

已补齐第一版增强：

- 每日或指定审计 JSONL 可通过 `anchor_audit_chain_tool` 写入独立 anchor 文件。
- anchor 文件可配置 `TMP_MCP_AUDIT_ANCHOR_SECRET` 使用 HMAC-SHA256 签名。
- `verify_audit_anchor_tool` 可校验当前审计文件是否仍匹配锚点。

后续增强：

- 定时自动锚定，而不是手工调用工具。
- 将 anchor 上传到集中审计服务或第三方透明日志。
- 借鉴 Rekor 的透明日志思路，借鉴 in-toto 的有序步骤和签名元数据。

### 验收用例

必须新增自动化测试：

- 连续写入三条审计事件，`prev_hash` 串联正确。
- `verify_audit_chain.py` 对原始日志返回通过。
- 修改第二行任意字段后，校验失败并定位行号。
- 删除第二行后，校验失败并定位 `prev_hash` 断裂。
- 含敏感字段的事件先脱敏再哈希，日志不出现明文 token。
- `verify_audit_anchor.py` 能证明锚点创建成功，原始文件通过，锚定后追加事件会失败，错误 HMAC 密钥会失败。

## trace 链路串联设计

### ID 生成原则

当前 `OperationContext` 已有 `session_id` 和 `trace_id` 字段。下一阶段建议：

- `trace_id`：如果调用方未传入，MCP 工具入口自动生成。
- `session_id`：如果 AstrBot 未提供，则用 `local-{date}` 或 `manual-{uuid}` 作为降级值。
- `event_id`：每条审计事件继续用独立 UUID。
- `parent_event_id`：下一阶段可选新增，用于表示工具结果归属于某条 guardrail decision。

建议格式：

```text
trace_id = 32 位十六进制字符串，兼容 W3C Trace Context 的 trace-id 形态
session_id = astrbot session id 或 tmp-mcp-local-YYYYMMDD
```

### 串联链路

一次写操作至少产生两类审计事件：

```text
guardrail_decision(trace_id=T)
-> tool_result(trace_id=T)
```

如果未来加入工具调用开始事件：

```text
tool_call(trace_id=T)
-> guardrail_decision(trace_id=T)
-> approval_required(trace_id=T)
-> tool_result(trace_id=T)
```

`get_audit_events_tool(trace_id=T)` 应返回同一链路的所有事件。

### 工具入口改造

建议新增：

```text
tmp_MCP/src/mcp_ops_server/tracing.py
```

核心函数：

```python
def ensure_trace_id(trace_id: str | None = None) -> str:
    ...

def ensure_session_id(session_id: str | None = None) -> str:
    ...

def build_trace_context(session_id: str | None, trace_id: str | None) -> TraceContext:
    ...
```

写工具 wrapper 中统一调用：

```python
trace = build_trace_context(session_id=session_id, trace_id=trace_id)
context = OperationContext(..., session_id=trace.session_id, trace_id=trace.trace_id)
```

### 与 AstrBot 的关系

AstrBot 当前日志中能看到工具名和工具参数，但不保证每次都传入 `trace_id`。因此 MCP Server 必须自己兜底生成。

推荐 AstrBot 测试提示词：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 request_network_policy_change，生成开放 tcp 8080 端口的 dry_run 计划，不要真实修改防火墙，并说明返回中的 trace_id 与 guardrail_decision。
```

随后：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 get_audit_events_tool，用上一步返回的 trace_id 查询审计链路。
```

### 验收用例

必须新增自动化测试：

- 不传 `trace_id` 调用写工具，返回结果中存在自动生成的 `trace_id`。
- `data.guardrail_decision` 与 `tool_result` 审计事件拥有相同 `trace_id`。
- `get_audit_events_tool(trace_id=...)` 能查回同一次调用的所有事件。
- 传入外部 `trace_id` 时不覆盖，继续透传。
- 上游 `guard_context.trace_id` 存在时，优先使用外部 trace 或记录映射关系。

## 推荐代码框架

下一轮代码建议按这个顺序落地：

```text
config/guardrails/rules.yaml
src/mcp_ops_server/guardrails/rule_schema.py
src/mcp_ops_server/guardrails/rule_loader.py
src/mcp_ops_server/audit/verifier.py
src/mcp_ops_server/tracing.py
scripts/verify_audit_chain.py
scripts/verify_guardrail_rules.py
```

改造现有文件：

```text
src/mcp_ops_server/guardrails/risk_engine.py
src/mcp_ops_server/audit/logger.py
src/mcp_ops_server/audit/models.py
src/mcp_ops_server/tool_groups/audit_tools.py
src/mcp_ops_server/tool_groups/execution_tools.py
```

## 答辩展示口径

可以这样说明：

- 规则库不是写死在代码里，而是维护在 `config/guardrails/rules.yaml`，每条规则都有来源、版本、建议和测试样例。
- 审计日志不是普通文本，而是 JSONL 哈希链；任意中间事件被改动都能被校验脚本发现。
- 每次工具调用都有 `trace_id`，能把“模型计划、安全决策、执行计划、最终结果”串成一条可回放时间线。
- `critical` 风险不能被审批绕过，`high` 风险真实执行必须有审批，dry-run 也必须审计。

## 创意来源

本路线图的设计来源包括：

- MCP 官方安全最佳实践：强调工具调用授权、用户同意、能力边界和审计责任。
- OWASP LLM Top 10：启发 Prompt Injection、越权诱导、敏感信息泄露的规则分类。
- OWASP MCP Top 10：启发 MCP 工具投毒、上下文注入、过度权限、跨工具链风险控制。
- NIST AI RMF：启发风险治理、可度量、可追溯和持续改进。
- W3C Trace Context 与 OpenTelemetry：启发 `trace_id` 形态和跨事件链路关联。
- W3C PROV：启发“谁在什么时候基于什么输入做了什么决策”的溯源表达。
- Sigma 与 YARA：启发安全规则配置化、规则元数据、规则测试样例的组织方式。
- OPA：启发“策略即代码”和规则与执行逻辑分离。
- in-toto 与 Sigstore Rekor：启发有序事件、签名元数据、透明日志和篡改证据。
- ReAct 与 Toolformer：启发把模型推理、工具调用、观察结果和下一步行动串成可审计链路。
