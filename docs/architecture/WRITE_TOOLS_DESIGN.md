# MCP 写操作工具设计说明

本文档设计 `tmp_MCP` 后续需要接入安全意图校验器的写操作工具。这里的“写操作”指任何可能改变系统状态的动作，例如修改文件、删除文件、重启服务、停止进程、修改权限、安装/卸载软件包、修改网络策略。

第一阶段只设计接口和安全约束，不建议直接实现真实执行。代码实现时应先返回“已接收申请 / 需要审批 / 已拒绝”，等安全意图校验器、审计日志、最小权限执行代理完成后，再逐步开放固定模板动作。

## 总体原则

- 不开放任意 shell 命令执行。
- 所有写工具都必须先调用安全意图校验器。
- 所有写工具都必须写审计日志。
- `critical` 风险默认拒绝，不进入审批。
- `high` 风险默认进入审批，不自动执行。
- 执行动作必须来自固定模板，不允许模型自由拼命令。
- Linux 和 Windows 使用不同执行后端，但对 MCP Client 暴露统一工具语义。
- 默认面向本机执行，远程执行必须显式传入 `target`，并记录目标。
- 所有修改类动作都必须考虑备份、回滚和幂等性。

## 当前 P1 实现状态

`0.4.0-alpha` 已完成第一版最小权限模板声明；当前进一步补充了受限执行代理档案，但还没有开放新的真实提权执行权限。

已落地能力：

- `execution/action_templates.py` 维护写操作白名单模板。
- `get_execution_action_templates_tool` 可查询模板清单或单个 action 的最小权限声明。
- `execution/agents/` 维护 Linux/麒麟 `ops-agent` 与 Windows JEA 的受限执行代理档案。
- `get_execution_agent_profiles_tool` 可查询代理档案、允许模板、禁止能力和部署样例路径。
- 所有 `request_*` dry-run 计划的 `data.least_privilege` 会返回对应模板上下文。
- 模板覆盖修改文件、删除文件、重启服务、停止进程、修改权限、包管理和网络策略变更。

当前边界：

- 不开放任意 shell。
- 不因模板存在而自动放行真实执行。
- 真实执行仍受 guardrail、`approval_id` 和固定模板限制。
- `reference_only` 代理档案不代表目标主机已部署；Linux `ops-agent` 实机安装、sudoers allowlist 验证和 Windows PowerShell JEA Endpoint 仍是下一步实现。

## 通用参数

所有写工具建议统一包含以下参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `target` | string | 否 | 默认 `local`，后续支持远程主机 |
| `platform_hint` | string | 否 | `auto`、`linux`、`windows` |
| `reason` | string | 是 | 用户或 Agent 给出的操作原因 |
| `dry_run` | bool | 否 | 默认 `true`，只做校验和计划生成 |
| `approval_id` | string | 否 | 审批通过后传入 |
| `operator` | string | 否 | 操作者标识，用于审计 |
| `session_id` | string | 否 | 会话标识，用于链路追踪 |

返回结构仍使用 `ToolEnvelope`：

```json
{
  "ok": false,
  "risk_level": "high",
  "summary": "Action requires approval and was not executed.",
  "data": {
    "action": "restart_service",
    "status": "approval_required",
    "plan": {},
    "least_privilege": {
      "template_id": "TPL_SERVICE_RESTART_V1",
      "enforced": true,
      "fixed_template_only": true,
      "recommended_runtime_account": "ops-agent with limited sudo systemctl rule",
      "allowed_scopes": [],
      "denied_scopes": [],
      "rollback_strategy": []
    },
    "post_checks": {},
    "rollback_hint": [],
    "guardrail": {}
  },
  "evidence": [],
  "next_actions": []
}
```

`dry_run=true` 时通常只返回计划和 `least_privilege`；当 `dry_run=false` 且审批与 `ExecutionPolicy` 都通过后，固定模板真实执行结果应补充 `post_checks / rollback_hint`。例如文件修改会返回 `pre_hash / post_hash / backup_path`，并在 `post_checks.checks[]` 中记录 `file_hash_changed`、`backup_created` 等检查项。

## 工具清单

| 工具名 | 动作 | Linux 后端 | Windows 后端 | 默认风险 |
| --- | --- | --- | --- | --- |
| `request_modify_file` | 修改文件 | 受控写入模板 | PowerShell 受控写入模板 | `high` |
| `request_delete_file` | 删除文件 | 移动到隔离区或删除模板 | 移动到隔离区或删除模板 | `high` |
| `request_restart_service` | 重启服务 | `systemctl restart` 模板 | `Restart-Service` 模板 | `high` |
| `request_stop_process` | 停止进程 | `kill` / `systemctl stop` 模板 | `Stop-Process` 模板 | `high` |
| `request_change_permissions` | 修改权限 | `chmod` / `chown` 模板 | ACL 模板 | `high` |
| `request_manage_package` | 安装/卸载软件包 | `apt/yum/dnf/zypper` 模板 | `winget` 或离线包模板 | `high` |
| `request_network_policy_change` | 修改网络策略 | `firewalld/iptables/nftables` 模板 | Windows Firewall 模板 | `high` |

## 最小权限模板查询工具

### `get_execution_action_templates_tool`

用途：查询写操作固定模板和最小权限声明。该工具是只读元数据查询，不会执行系统命令。

参数：

```json
{
  "action": "network_policy_change",
  "platform_hint": "windows"
}
```

返回重点：

- `template_id`：固定动作模板编号。
- `recommended_linux_account`：建议 Linux 受限账户或 sudoers 规则方向。
- `recommended_windows_identity`：建议 Windows 受限身份或 JEA Endpoint 方向。
- `requires_elevation`：是否可能需要受控提权。
- `allowed_scopes`：允许范围。
- `denied_scopes`：禁止范围。
- `pre_checks` / `post_checks`：执行前后检查。
- `rollback_strategy`：回滚策略。

AstrBot 提示词：

```text
只允许通过 MCP 工具调用，不要使用 shell。调用 get_execution_action_templates_tool，查询 request_network_policy_change 对应的最小权限模板声明。
```

## 文件修改工具

### `request_modify_file`

用途：对指定文件做受控修改，例如替换配置项、追加一行配置、写入经过校验的内容。

参数：

```json
{
  "path": "/etc/nginx/nginx.conf",
  "operation": "replace_text",
  "content": "worker_processes auto;",
  "match": "worker_processes 1;",
  "backup": true,
  "target": "local",
  "platform_hint": "linux",
  "reason": "修复 nginx worker 配置",
  "dry_run": true,
  "approval_id": null
}
```

支持的 `operation`：

- `replace_text`：替换明确文本
- `append_line`：追加单行
- `set_key_value`：修改 `key=value` 配置
- `comment_line`：注释匹配行

禁止：

- 直接覆盖整个系统配置文件
- 写入二进制内容
- 写入包含命令执行片段的内容
- 修改 `/boot`、内核模块、系统认证文件等 critical 路径

Linux 模板：

- 修改前执行 `stat` 和 hash 记录
- 创建 `.bak` 备份
- 使用临时文件写入
- 原子替换
- 修改后再次 hash

Windows 模板：

- 修改前读取 ACL、大小、hash
- 创建 `.bak` 备份
- 使用 PowerShell `Set-Content` 或 `.NET` 安全写入
- 修改后再次 hash

回滚要求：

- 必须记录备份路径
- 必须提供 `rollback_modify_file` 的后续设计入口
- 真实执行返回必须包含 `pre_hash / post_hash / backup_path`、`post_checks` 和 `rollback_hint`

## 文件删除工具

### `request_delete_file`

用途：删除或隔离明确文件。默认不做真实删除，优先移动到隔离区。

参数：

```json
{
  "path": "/var/log/app/old.log",
  "mode": "quarantine",
  "recursive": false,
  "target": "local",
  "platform_hint": "linux",
  "reason": "释放日志占用空间",
  "dry_run": true,
  "approval_id": null
}
```

支持的 `mode`：

- `quarantine`：移动到隔离区，推荐默认
- `archive`：压缩归档后移走
- `truncate`：只截断日志文件，适合部分服务日志
- `delete`：真实删除，默认不开放

禁止：

- 删除目录根路径
- 删除带通配符路径
- 默认递归删除
- 删除数据库数据目录
- 删除系统目录
- 删除符号链接指向的真实敏感路径

Linux 模板：

- `quarantine`：移动到 `/var/tmp/tmp_mcp_quarantine/`
- `archive`：压缩到 `/var/tmp/tmp_mcp_archive/`
- `truncate`：只允许明确日志文件

Windows 模板：

- `quarantine`：移动到 `%ProgramData%\tmp_mcp\quarantine\`
- `archive`：压缩到 `%ProgramData%\tmp_mcp\archive\`
- `truncate`：只允许明确日志文件

回滚要求：

- `quarantine` 和 `archive` 必须可恢复
- `delete` 必须要求二次审批，不建议比赛第一版实现

## 服务重启工具

### `request_restart_service`

用途：重启单个明确服务。

参数：

```json
{
  "service": "nginx",
  "target": "local",
  "platform_hint": "linux",
  "reason": "配置变更后重载服务",
  "dry_run": true,
  "approval_id": null
}
```

禁止：

- 批量重启服务
- 重启核心系统服务，例如 `sshd`、`network`、`firewalld`、`winrm`
- 用自由命令替代服务名
- 服务名包含 shell 特殊字符

Linux 模板：

- 前置检查：`systemctl status <service>`
- 计划动作：优先 `systemctl reload`，不支持时才 `restart`
- 后置检查：服务状态、最近日志

Windows 模板：

- 前置检查：`Get-Service -Name <service>`
- 计划动作：`Restart-Service -Name <service>`
- 后置检查：服务状态、事件日志摘要

回滚要求：

- 服务重启没有严格回滚，必须提供失败后的诊断建议
- 对业务关键服务必须先提示影响窗口

## 停止进程工具

### `request_stop_process`

用途：停止单个明确 PID 或明确进程名。优先建议通过服务管理停止，而不是直接 kill。

参数：

```json
{
  "pid": 1234,
  "process_name": "worker",
  "signal": "terminate",
  "target": "local",
  "platform_hint": "linux",
  "reason": "疑似僵尸进程占用资源",
  "dry_run": true,
  "approval_id": null
}
```

支持的 `signal`：

- `terminate`：温和停止，默认
- `kill`：强制停止，需要更高风险审批

禁止：

- 停止 PID 1
- 停止系统关键进程
- 按模糊名称批量停止
- 停止安全软件、数据库、SSH/WinRM 等关键远程访问进程

Linux 模板：

- 前置检查：`ps`、父进程、用户、命令行
- 执行动作：`kill -TERM <pid>`，强制时 `kill -KILL <pid>`
- 后置检查：进程是否仍存在

Windows 模板：

- 前置检查：`Get-Process -Id <pid>`
- 执行动作：`Stop-Process -Id <pid>`，强制时增加 `-Force`
- 后置检查：进程是否仍存在

回滚要求：

- 停止进程通常不可回滚
- 若进程属于服务，建议改用服务重启工具

## 权限修改工具

### `request_change_permissions`

用途：对明确文件或目录做最小范围权限修复。

参数：

```json
{
  "path": "/etc/nginx/nginx.conf",
  "mode": "0640",
  "owner": "root",
  "group": "nginx",
  "recursive": false,
  "target": "local",
  "platform_hint": "linux",
  "reason": "修复 nginx 配置文件权限",
  "dry_run": true,
  "approval_id": null
}
```

禁止：

- `chmod 777`
- `chmod 000`
- 对系统目录递归改权限
- 对数据库目录递归改属主
- Windows 下给 `Everyone FullControl`

Linux 模板：

- `chmod <mode> <path>`
- `chown <owner>:<group> <path>`
- 默认不允许 `recursive=true`

Windows 模板：

- 使用 `icacls` 或 PowerShell ACL API
- 只允许明确 SID/用户
- 禁止给 `Everyone`、`Users` 过宽权限

回滚要求：

- 修改前记录原始权限、属主或 ACL
- 审计日志必须能用于恢复

## 软件包管理工具

### `request_manage_package`

用途：安装、升级或卸载明确软件包。

参数：

```json
{
  "manager": "auto",
  "action": "install",
  "package": "lsof",
  "version": null,
  "target": "local",
  "platform_hint": "linux",
  "reason": "补齐运维诊断依赖",
  "dry_run": true,
  "approval_id": null
}
```

支持的 `action`：

- `install`
- `upgrade`
- `remove`

禁止：

- 批量安装未知包
- 从未知 URL 下载并执行安装脚本
- 卸载系统关键包
- 跳过签名验证

Linux 模板：

- 麒麟/统信等国产 Linux 可优先识别 `dnf`、`yum`、`apt`、`zypper`
- 安装前执行 dry-run 或查询包信息
- 卸载前列出反向依赖

Windows 模板：

- 优先 `winget` 查询明确包 ID
- 企业环境可设计离线包白名单
- 卸载前记录版本和安装路径

回滚要求：

- 安装/升级前记录当前版本
- 卸载前记录恢复方式

## 网络策略修改工具

### `request_network_policy_change`

用途：添加、删除或启停明确网络访问规则，例如开放端口、关闭端口、限制来源 IP。

参数：

```json
{
  "action": "allow_port",
  "protocol": "tcp",
  "port": 8080,
  "source": "10.0.0.0/24",
  "target": "local",
  "platform_hint": "linux",
  "reason": "允许内网访问应用服务",
  "dry_run": true,
  "approval_id": null
}
```

支持的 `action`：

- `allow_port`
- `deny_port`
- `allow_source`
- `deny_source`
- `disable_rule`
- `enable_rule`

第一版代码实际执行模板只实现 `allow_port` 和 `deny_port`，同时兼容以下自然别名：

- `allow`、`open`、`add`、`permit`、`enable` -> `allow_port`
- `deny`、`block`、`close`、`remove`、`drop`、`disable` -> `deny_port`

禁止：

- 关闭全部防火墙
- 开放全部端口
- 开放 `0.0.0.0/0` 到敏感端口
- 禁用 SSH/WinRM 远程访问通道
- 清空全部规则

Linux 模板：

- 优先识别 `firewalld`
- 其次支持 `nftables` 或 `iptables`
- 修改前导出当前规则
- 修改后验证端口策略

Windows 模板：

- 使用 `New-NetFirewallRule`、`Set-NetFirewallRule`
- 修改前导出现有规则摘要
- 修改后验证规则状态

回滚要求：

- 每次变更必须记录规则 ID
- 必须能删除本次新增规则或恢复旧规则

## 双系统适配策略

### Linux / 麒麟

优先支持：

- `systemctl`
- `journalctl`
- `ss`
- `lsof`
- `stat`
- `sha256sum`
- `firewall-cmd`
- `dnf` / `yum` / `apt`

注意事项：

- 麒麟高级服务器版 V11 可能使用 systemd，但包管理和默认仓库策略需现场验证。
- LoongArch 环境下 Python 包和系统命令路径可能不同，需要平台自检工具辅助判断。
- 不应假设所有命令都存在，工具应返回缺失依赖说明。

### Windows Server

优先支持：

- PowerShell 5+ 或 PowerShell 7+
- `Get-Service` / `Restart-Service`
- `Get-Process` / `Stop-Process`
- `Get-FileHash`
- `Get-Acl` / `Set-Acl`
- `New-NetFirewallRule`
- `winget` 或企业离线包策略

注意事项：

- 部分命令需要管理员权限。
- WinRM 远程执行必须显式开启并记录目标。
- Windows 服务名和显示名不同，工具应优先使用服务名。

## 与安全意图校验器的接入点

每个写工具执行前都需要构造校验输入：

```json
{
  "tool_name": "request_delete_file",
  "operation": "delete_file",
  "target": "local",
  "platform_hint": "linux",
  "path": "/var/log/app/old.log",
  "command_template": "quarantine_file",
  "reason": "释放日志占用空间"
}
```

校验结果处理：

- `deny`：直接返回 `ok=false`，不进入审批。
- `require_approval`：返回审批申请信息，不执行。
- `allow`：如果是低风险只读动作可继续；写动作仍建议至少要求审批。

## 建议实现顺序

1. 先保留现有 `request_restart_service` 和 `request_log_cleanup` 占位行为。
2. 新增 `request_delete_file`，但第一版只允许 `dry_run=true` 和 `mode=quarantine` 计划生成。
3. 新增 `request_modify_file`，第一版只输出修改计划和备份计划。
4. 新增 `request_change_permissions`，第一版只输出权限差异计划。
5. 新增 `request_stop_process`，第一版只输出进程停止风险评估。
6. 新增 `request_manage_package` 和 `request_network_policy_change`，第一版仅生成计划，不执行。

## 验收标准

- 每个写工具都有明确工具名、参数、风险等级和双系统执行模板。
- 每个写工具都说明禁止场景和回滚要求。
- 文档中没有建议开放任意 shell。
- 默认 `dry_run=true`，未审批不执行。
- 可以直接据此拆分后续 Python 代码任务。
