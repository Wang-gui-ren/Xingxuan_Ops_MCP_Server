from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ASTRBOT_ROOT = ROOT.parent / "tmp_astrbot"

for candidate in (SRC, ASTRBOT_ROOT, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from astrbot.core.message.message_event_result import MessageEventResult  # noqa: E402
from integrations.astrbot_filesystem_command.main import TmpMcpFilesystemPlugin  # noqa: E402


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, object]] = []

    async def call(self, _ctx, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "ok": True,
            "summary": f"{self.name} dry-run planned",
            "data": {"tool_name": self.name, "arguments": kwargs},
        }
        return _fake_result(json.dumps(payload, ensure_ascii=False))


class MissingToolManager:
    def get_func(self, _name: str):
        return None


class FakeToolManager:
    def __init__(self) -> None:
        self.tools = {
            "request_create_file": FakeTool("request_create_file"),
            "request_create_directory": FakeTool("request_create_directory"),
            "request_restart_service": FakeTool("request_restart_service"),
            "request_network_policy_change": FakeTool("request_network_policy_change"),
            "request_log_cleanup": FakeTool("request_log_cleanup"),
            "get_host_profile_tool": FakeTool("get_host_profile_tool"),
        }

    def get_func(self, name: str):
        return self.tools.get(name)


class FakeContext:
    def __init__(self, tool_manager) -> None:
        self._tool_manager = tool_manager

    def get_llm_tool_manager(self):
        return self._tool_manager


class FakeEvent:
    def __init__(self, message: str) -> None:
        self.message_str = message
        self.session_id = "verify-session"
        self.call_llm = True
        self._stopped = False
        self._result = None
        self.llm_flags: list[bool] = []

    def should_call_llm(self, call_llm: bool) -> None:
        self.call_llm = call_llm
        self.llm_flags.append(call_llm)

    def set_result(self, result: MessageEventResult) -> None:
        self._result = result

    def stop_event(self) -> None:
        self._stopped = True

    def is_stopped(self) -> bool:
        return self._stopped

    def get_result(self):
        return self._result


def _fake_result(text: str):
    class TextItem:
        type = "text"

        def __init__(self, value: str) -> None:
            self.text = value

    class Result:
        def __init__(self, value: str) -> None:
            self.content = [TextItem(value)]

    return Result(text)


async def _run_intercept_case(
    *,
    plugin: TmpMcpFilesystemPlugin,
    tool_manager: FakeToolManager,
    case_name: str,
    message: str,
    expected_tool: str,
    required_argument_key: str | None = None,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    tool = tool_manager.tools[expected_tool]
    previous_call_count = len(tool.calls)
    event = FakeEvent(message)
    await plugin.on_message_event(event)

    check(checks, event.llm_flags == [False], f"{case_name}: should_call_llm(false)")
    check(checks, event.is_stopped(), f"{case_name}: event stopped")
    result = event.get_result()
    check(checks, isinstance(result, MessageEventResult), f"{case_name}: MessageEventResult set")
    check(checks, len(tool.calls) == previous_call_count + 1, f"{case_name}: tool call count incremented")
    if required_argument_key:
        call_payload = tool.calls[-1] if tool.calls else {}
        check(checks, required_argument_key in call_payload, f"{case_name}: required argument present")
    if isinstance(result, MessageEventResult):
        plain_text = result.get_plain_text()
        check(checks, expected_tool in plain_text, f"{case_name}: result mentions tool name")
    return checks


async def _run_missing_tool_case(plugin_cls) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    plugin = plugin_cls(FakeContext(MissingToolManager()))
    event = FakeEvent("重启 Spooler 服务")
    await plugin.on_message_event(event)
    check(checks, event.llm_flags == [False], "missing tool: should_call_llm(false)")
    check(checks, event.is_stopped(), "missing tool: event stopped")
    result = event.get_result()
    check(checks, isinstance(result, MessageEventResult), "missing tool: result exists")
    if isinstance(result, MessageEventResult):
        check(checks, "未发现 request_restart_service" in result.get_plain_text(), "missing tool: deterministic setup error returned")
    return checks


async def _run_complex_question_case(plugin: TmpMcpFilesystemPlugin) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    event = FakeEvent("帮我看看 nginx 为什么不可用")
    await plugin.on_message_event(event)
    check(checks, event.llm_flags == [], "complex question: bridge does not force llm false")
    check(checks, not event.is_stopped(), "complex question: event not stopped")
    check(checks, event.get_result() is None, "complex question: no direct result")
    return checks


def check(checks: list[dict[str, str]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


async def _amain() -> None:
    checks: list[dict[str, str]] = []
    tool_manager = FakeToolManager()
    plugin = TmpMcpFilesystemPlugin(FakeContext(tool_manager))

    for case_checks in (
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_create_file",
            message="在 G:\\完整mcp 中建立一个文件 111.json",
            expected_tool="request_create_file",
            required_argument_key="path",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_create_directory",
            message="在 C:\\tmp 这个文件夹新建一个空文件夹：名字叫 test1",
            expected_tool="request_create_directory",
            required_argument_key="path",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_restart_service_local",
            message="重启 Spooler 服务",
            expected_tool="request_restart_service",
            required_argument_key="service",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_network_policy_change",
            message="开放 tcp 8080 端口",
            expected_tool="request_network_policy_change",
            required_argument_key="port",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_log_cleanup",
            message="归档 /var/log/nginx/access.log",
            expected_tool="request_log_cleanup",
            required_argument_key="path",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="get_host_profile_tool_local",
            message="查询电脑配置",
            expected_tool="get_host_profile_tool",
            required_argument_key="target",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="get_host_profile_tool_remote",
            message="查看远程 linux 服务器 192.168.1.20 用户 ops 端口 22 主机画像",
            expected_tool="get_host_profile_tool",
            required_argument_key="target",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_restart_service_remote",
            message="重启远程 linux 服务器 192.168.1.20 上的 nginx 服务 用户 ops 端口 22",
            expected_tool="request_restart_service",
            required_argument_key="target",
        ),
        await _run_intercept_case(
            plugin=plugin,
            tool_manager=tool_manager,
            case_name="request_restart_service_remote_windows",
            message="重启远程 windows 服务器 win-server-01 上的 Spooler 服务 账号 admin 端口 5985",
            expected_tool="request_restart_service",
            required_argument_key="target",
        ),
        await _run_complex_question_case(plugin),
        await _run_missing_tool_case(TmpMcpFilesystemPlugin),
    ):
        checks.extend(case_checks)

    failed = [item for item in checks if item["status"] != "PASS"]
    payload = {
        "total": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


def main() -> None:
    import asyncio

    asyncio.run(_amain())


if __name__ == "__main__":
    main()
