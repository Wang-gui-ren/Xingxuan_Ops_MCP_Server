# AstrBot 确定性运维桥接手工验证

## 目标

验证 AstrBot 与 `星璇运维MCP` 文件系统桥接插件的基础联通性。

## 插件目录

- 新默认目录：`astrbot_plugin_xingxuan_mcp_filesystem`
- 旧目录兼容：`astrbot_plugin_tmp_mcp_filesystem`

## 手工步骤

1. 在 AstrBot 插件目录安装文件系统桥接插件。
2. 重载或重新加载 `astrbot_plugin_xingxuan_mcp_filesystem`。
3. 发送一个确定性本地运维请求。

## 预期日志

- `星璇运维MCP deterministic ops bridge loaded.`
- `星璇运维MCP deterministic ops bridge intercepted. tool=request_create_directory`

## 预期结果

- 请求不进入普通 LLM 流程。
- 返回内容来自固定 MCP 工具。
- 结果应包含 `status=planned`、`approval_request` 和 `trace_id` 等字段。
