from __future__ import annotations

from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.core.agent.run_context import ContextWrapper

from .intent_parser import DeterministicIntent, parse_intent


@star.register(
    "astrbot_plugin_xingxuan_mcp_filesystem",
    "星璇运维MCP",
    "Route deterministic local ops requests to 星璇运维MCP without entering the LLM pipeline.",
    "0.2.0",
)
class TmpMcpFilesystemPlugin(star.Star):
    def __init__(self, context: star.Context) -> None:
        super().__init__(context)
        logger.info("星璇运维MCP deterministic ops bridge loaded.")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10_000)
    async def on_message_event(self, event: AstrMessageEvent) -> None:
        text = (event.message_str or "").strip()
        if not text:
            return
        intent = parse_intent(text)
        if intent is None:
            return

        logger.info(
            "星璇运维MCP deterministic ops bridge intercepted. tool=%s message=%r session=%s",
            intent.tool_name,
            event.message_str,
            event.session_id,
        )
        event.should_call_llm(False)

        payload = await self._call_mcp_tool(intent)
        event.set_result(
            MessageEventResult()
            .message(payload)
            .use_t2i(False)
            .stop_event()
        )
        event.stop_event()

    async def _call_mcp_tool(self, intent: DeterministicIntent) -> str:
        tool_manager = self.context.get_llm_tool_manager()
        tool = tool_manager.get_func(intent.tool_name)
        if tool is None:
            return (
                f"未发现 {intent.tool_name}。\n"
                f"请确认星璇运维MCP 服务已连接，并且工具列表中包含 {intent.tool_name}。"
            )

        try:
            result = await tool.call(
                ContextWrapper(context=None, tool_call_timeout=60),
                **intent.arguments,
            )
        except Exception as exc:  # noqa: BLE001
            return f"{intent.summary} 计划生成失败：{exc}"

        payload = _extract_text_payload(result)
        return payload or f"{intent.summary} 工具已执行，但没有返回可读文本。"


def _extract_text_payload(result: Any) -> str | None:
    content_items = getattr(result, "content", None) or []
    text_parts = [
        str(getattr(item, "text", ""))
        for item in content_items
        if getattr(item, "type", None) == "text" and getattr(item, "text", None)
    ]
    if not text_parts:
        return None
    return "\n".join(part.strip() for part in text_parts if part.strip()).strip() or None
