# Guardrail 规则库

本目录维护 `tmp_MCP` 安全意图校验器的配置化规则。默认规则文件为 `rules.yaml`。

维护约定：

- 每条规则必须包含 `id / category / risk_level / pattern / enabled / version / source / recommendation / test_cases`。
- `enabled=false` 的规则不会参与运行时匹配，但仍保留在规则库中便于解释和回归。
- 修改规则后运行 `scripts/verify_guardrail_rules.py` 和 `scripts/verify_mcp_operations.py`。
- 当前运行时优先加载 `TMP_MCP_GUARDRAIL_RULES_FILE` 指向的规则文件；未配置时加载本目录默认规则。
- 如果规则文件缺失或加载失败，系统会回退到 Python 内置规则，避免 MCP Server 因配置错误无法启动。
