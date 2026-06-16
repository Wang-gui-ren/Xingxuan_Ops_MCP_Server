# AstrBot `/approvals` Command Bridge

This plugin maps AstrBot `/approvals` directly to
`星璇运维MCP`'s `open_approval_console_tool`.

## Install

```powershell
$env:PYTHONPATH="G:\完整mcp\tmp_mcp\src"
D:\miniconda\envs\astrbot\python.exe G:\完整mcp\tmp_mcp\scripts\install_astrbot_approvals_plugin.py --astrbot-plugins-dir G:\完整mcp\tmp_astrbot\data\plugins --force
```

## Expected behavior

- `/approvals` returns the approval console URL directly.
- `/approvals card` returns a PNG share card with URL, QR code and status text.
- The plugin only opens or reuses the hosted B/S gateway.
- It does not approve operations, mint tokens, or reveal the admin token.

## Compatibility

- New plugin ID: `astrbot_plugin_xingxuan_mcp_approvals`
- Legacy plugin ID: `astrbot_plugin_tmp_mcp_approvals`
