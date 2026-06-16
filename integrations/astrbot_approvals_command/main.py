from __future__ import annotations

import json
import os
import random
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.core.agent.run_context import ContextWrapper

CARD_CONFIG_FILE = "card_backgrounds.json"
DEFAULT_PROVERBS = [
    "星月朦胧，不雨也风。",
    "月晕而风，础润而雨。",
    "日晕三更雨，月晕午时风。",
    "斗柄东指，天下皆春。",
    "群星有界，探索无涯。",
    "仰观星河，心向远方。",
    "星光不问赶路人。",
    "星河灿烂，自有方向。",
]


@dataclass
class ApprovalConsoleOpenResult:
    ok: bool
    message: str
    approvals_url: str | None = None
    gateway: dict[str, Any] | None = None


@dataclass
class ApprovalCommandArgs:
    approval_id: str | None = None
    status: str | None = None
    render_mode: str = "text"


@star.register(
    "astrbot_plugin_xingxuan_mcp_approvals",
    "星璇运维MCP",
    "Reply with the 星璇运维MCP approval console URL when the user enters /approvals.",
    "0.4.1",
)
class TmpMcpApprovalsPlugin(star.Star):
    def __init__(self, context: star.Context) -> None:
        super().__init__(context)
        logger.info("星璇运维MCP approvals plugin loaded.")

    @filter.command("approvals")
    async def approvals(
        self,
        event: AstrMessageEvent,
        arg1: str | None = None,
        arg2: str | None = None,
        arg3: str | None = None,
    ) -> None:
        logger.info(
            "星璇运维MCP approvals command intercepted. message=%r session=%s",
            event.message_str,
            event.session_id,
        )
        event.should_call_llm(False)
        args = _parse_command_args(arg1, arg2, arg3)
        opened = await self._open_approval_console(
            approval_id=args.approval_id,
            status=args.status,
        )

        if args.render_mode == "card" and opened.ok and opened.approvals_url:
            card_path = _build_share_card(
                approvals_url=opened.approvals_url,
                approval_id=args.approval_id,
                status=args.status,
                gateway=opened.gateway or {},
            )
            if card_path:
                event.set_result(
                    MessageEventResult()
                    .file_image(str(card_path))
                    .message(f"\n审批台网址：\n{opened.approvals_url}")
                    .use_t2i(False)
                    .stop_event()
                )
                event.stop_event()
                return

        event.set_result(
            MessageEventResult()
            .message(opened.message)
            .use_t2i(False)
            .stop_event()
        )
        event.stop_event()

    async def _open_approval_console(
        self,
        approval_id: str | None,
        status: str | None,
    ) -> ApprovalConsoleOpenResult:
        tool_manager = self.context.get_llm_tool_manager()
        tool = tool_manager.get_func("open_approval_console_tool")
        if tool is None:
            return ApprovalConsoleOpenResult(
                ok=False,
                message=(
                    "未发现 open_approval_console_tool。\n"
                    "请确认星璇运维MCP 服务已连接，并且工具列表中包含 open_approval_console_tool。"
                ),
            )

        call_args: dict[str, Any] = {"limit": 20}
        if approval_id:
            call_args["approval_id"] = approval_id
        if status:
            call_args["status"] = status

        try:
            result = await tool.call(
                ContextWrapper(context=None, tool_call_timeout=60),
                **call_args,
            )
        except Exception as exc:  # noqa: BLE001
            return ApprovalConsoleOpenResult(
                ok=False,
                message=f"审批台启动失败：{exc}",
            )

        payload = _parse_mcp_text_payload(result)
        if not payload:
            return ApprovalConsoleOpenResult(
                ok=False,
                message="审批台工具已返回，但结果不是可解析的 JSON。请查看 AstrBot MCP 调用日志。",
            )

        gateway = payload.get("data", {}).get("gateway", {})
        if not payload.get("ok"):
            summary = payload.get("summary") or "审批台启动失败。"
            error = gateway.get("error") if isinstance(gateway, dict) else None
            message = f"{summary}\n{error}" if error else str(summary)
            return ApprovalConsoleOpenResult(
                ok=False,
                message=message,
                gateway=gateway if isinstance(gateway, dict) else {},
            )

        approvals_url = payload.get("data", {}).get("approvals_url")
        if not approvals_url:
            return ApprovalConsoleOpenResult(
                ok=False,
                message="审批台工具已成功执行，但响应中没有 data.approvals_url。",
                gateway=gateway if isinstance(gateway, dict) else {},
            )

        return ApprovalConsoleOpenResult(
            ok=True,
            message=_plain_url_message(
                approvals_url=str(approvals_url),
                approval_id=approval_id,
                status=status,
                gateway=gateway if isinstance(gateway, dict) else {},
            ),
            approvals_url=str(approvals_url),
            gateway=gateway if isinstance(gateway, dict) else {},
        )


def _parse_command_args(*raw_args: str | None) -> ApprovalCommandArgs:
    parsed = ApprovalCommandArgs()
    status_values = {
        "all",
        "open",
        "requested",
        "partially_granted",
        "granted",
        "rejected",
        "revoked",
        "expired",
    }
    card_values = {"card", "image", "img", "poster", "pic", "图片", "卡片", "海报"}
    text_values = {"text", "url", "link", "plain", "网址", "链接", "文本"}

    for raw in raw_args:
        value = str(raw or "").strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in card_values:
            parsed.render_mode = "card"
        elif lowered in text_values:
            parsed.render_mode = "text"
        elif lowered in status_values:
            parsed.status = lowered
        elif parsed.approval_id is None:
            parsed.approval_id = value
        elif parsed.status is None:
            parsed.status = value

    return parsed


def _plain_url_message(
    approvals_url: str,
    approval_id: str | None,
    status: str | None,
    gateway: dict[str, Any],
) -> str:
    started = bool(gateway.get("started"))
    reused = bool(gateway.get("reused_existing"))
    if started:
        gateway_state = "新启动"
    elif reused:
        gateway_state = "已复用"
    else:
        gateway_state = "可访问"

    lines = [
        "审批台已就绪，请在浏览器打开：",
        approvals_url,
        "",
        f"网关状态：{gateway_state}",
    ]
    if approval_id:
        lines.append(f"审批 ID：{approval_id}")
    if status:
        lines.append(f"队列状态：{status}")
    lines.append("说明：这里只返回网址，不会自动批准操作。")
    return "\n".join(lines)


def _parse_mcp_text_payload(result: Any) -> dict[str, Any] | None:
    content_items = getattr(result, "content", None) or []
    text_parts = [
        str(getattr(item, "text", ""))
        for item in content_items
        if getattr(item, "type", None) == "text" and getattr(item, "text", None)
    ]
    if not text_parts:
        return None

    try:
        payload = json.loads("\n".join(text_parts).strip())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _build_share_card(
    approvals_url: str,
    approval_id: str | None,
    status: str | None,
    gateway: dict[str, Any],
) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
        import qrcode
    except Exception:
        return None

    size = (1200, 720)
    card_config = _load_card_config()
    seed_text = approval_id or approvals_url
    proverb = _choose_proverb(card_config)
    img = _build_background_canvas(
        Image=Image,
        ImageDraw=ImageDraw,
        ImageFilter=ImageFilter,
        size=size,
        seed_text=seed_text,
        card_config=card_config,
    )

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle((84, 74, 1116, 646), radius=34, fill=(17, 26, 40, 46))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(shadow)

    glass = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glass)
    gdraw.rounded_rectangle((78, 64, 1110, 636), radius=34, fill=(255, 255, 255, 222))
    gdraw.rounded_rectangle(
        (78, 64, 1110, 636),
        radius=34,
        outline=(221, 233, 248, 255),
        width=2,
    )
    gdraw.rounded_rectangle((118, 110, 202, 194), radius=22, fill=(17, 131, 210, 255))
    img.alpha_composite(glass)

    draw = ImageDraw.Draw(img)
    title_font = _font(ImageFont, 46, bold=True)
    sub_font = _font(ImageFont, 25)
    body_font = _font(ImageFont, 25)
    small_font = _font(ImageFont, 20)
    mono_font = _font(ImageFont, 22)

    draw.text((145, 130), "M", font=_font(ImageFont, 42, bold=True), fill=(255, 255, 255, 255))
    draw.text((228, 104), "星璇运维MCP 审批台", font=title_font, fill="#12263d")
    draw.text((230, 166), "人工审批入口已准备就绪", font=sub_font, fill="#607080")

    chip_text = "新启动" if gateway.get("started") else "已复用" if gateway.get("reused_existing") else "可访问"
    draw.rounded_rectangle((228, 222, 374, 264), radius=14, fill="#e8f4ff", outline="#9fd0ff")
    draw.text((252, 229), chip_text, font=small_font, fill="#0a74c5")

    if approval_id:
        draw.rounded_rectangle((392, 222, 690, 264), radius=14, fill="#f6f9fc", outline="#d8e4ef")
        draw.text(
            (414, 229),
            _short_text(f"审批 ID: {approval_id}", 22),
            font=small_font,
            fill="#526273",
        )
    if status:
        draw.rounded_rectangle((708, 222, 900, 264), radius=14, fill="#f6f9fc", outline="#d8e4ef")
        draw.text((730, 229), f"状态: {status}", font=small_font, fill="#526273")

    draw.text((228, 318), "请复制或点击以下地址打开：", font=body_font, fill="#223a50")
    url_lines = _wrap_text(draw, approvals_url, mono_font, 620)
    y = 362
    for line in url_lines[:3]:
        draw.text((228, y), line, font=mono_font, fill="#0d67b5")
        y += 32

    draw.text((228, 520), f"谚语：{proverb}", font=small_font, fill="#6a7787")
    draw.text((228, 552), "说明：这张卡片只展示入口，不会自动批准操作。", font=small_font, fill="#6a7787")
    draw.text(
        (228, 584),
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        font=small_font,
        fill="#8793a1",
    )

    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(approvals_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#0d67b5", back_color="white").convert("RGBA")
    qr_img = qr_img.resize((252, 252))
    qr_box = Image.new("RGBA", (292, 292), (255, 255, 255, 255))
    qdraw = ImageDraw.Draw(qr_box)
    qdraw.rounded_rectangle(
        (0, 0, 291, 291),
        radius=24,
        fill=(255, 255, 255, 255),
        outline=(207, 226, 244, 255),
        width=2,
    )
    qr_box.alpha_composite(qr_img, (20, 20))
    img.alpha_composite(qr_box, (784, 280))
    draw = ImageDraw.Draw(img)
    draw.text((846, 584), "扫码打开", font=small_font, fill="#526273")

    output_dir = Path(
        os.getenv("TMP_MCP_APPROVAL_CARD_DIR")
        or Path(tempfile.gettempdir()) / "tmp_mcp_approval_cards"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "approval_console_card.png"
    img.convert("RGB").save(output_path, "PNG")
    return output_path


def _build_background_canvas(
    *,
    Image: Any,
    ImageDraw: Any,
    ImageFilter: Any,
    size: tuple[int, int],
    seed_text: str,
    card_config: dict[str, Any],
) -> Any:
    image_path = _choose_background_image(seed_text, card_config)
    if image_path is not None:
        try:
            background = Image.open(image_path).convert("RGB")
            background = _resize_cover(background, size, Image)
            background = background.filter(ImageFilter.GaussianBlur(1.2))
            result = background.convert("RGBA")
            result.alpha_composite(Image.new("RGBA", size, (14, 24, 42, 54)))
            result.alpha_composite(_soft_highlight(Image, ImageDraw, size))
            logger.info("星璇运维MCP approval card uses background image: %s", image_path)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("星璇运维MCP approval card background failed: %s", exc)

    return _gradient_background(Image, ImageDraw, size)


def _gradient_background(Image: Any, ImageDraw: Any, size: tuple[int, int]) -> Any:
    width, height = size
    img = Image.new("RGB", size, "#eef7ff")
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / max(height - 1, 1)
        red = int(238 + 10 * ratio)
        green = int(247 - 12 * ratio)
        blue = int(255 - 18 * ratio)
        draw.line([(0, y), (width, y)], fill=(red, green, blue))

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse((-160, -120, 360, 360), fill=(79, 172, 254, 42))
    odraw.ellipse((820, 430, 1320, 930), fill=(255, 138, 184, 46))
    odraw.ellipse((780, -80, 1240, 280), fill=(126, 211, 255, 35))
    base = Image.alpha_composite(img.convert("RGBA"), overlay)
    base.alpha_composite(_soft_highlight(Image, ImageDraw, size))
    return base


def _soft_highlight(Image: Any, ImageDraw: Any, size: tuple[int, int]) -> Any:
    highlight = Image.new("RGBA", size, (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hdraw.ellipse((-60, -180, 560, 380), fill=(255, 255, 255, 58))
    hdraw.ellipse((720, -120, 1320, 320), fill=(255, 235, 190, 42))
    hdraw.rectangle((0, 520, size[0], size[1]), fill=(255, 255, 255, 16))
    return highlight


def _load_card_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().with_name(CARD_CONFIG_FILE)
    if not config_path.exists():
        return {}

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("星璇运维MCP approval card config read failed: %s", exc)
        return {}

    return payload if isinstance(payload, dict) else {}


def _load_background_candidates(card_config: dict[str, Any] | None = None) -> list[Path]:
    config = card_config or _load_card_config()
    config_path = Path(__file__).resolve().with_name(CARD_CONFIG_FILE)
    base_dir = config_path.parent

    raw_paths = [
        str(item).strip()
        for item in config.get("background_paths", [])
        if isinstance(item, str) and item.strip()
    ]

    env_paths = os.getenv("TMP_MCP_APPROVAL_CARD_BACKGROUNDS", "").strip()
    if env_paths:
        raw_paths = [part.strip() for part in env_paths.split(os.pathsep) if part.strip()]

    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in raw_paths:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        normalized = str(path).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if path.exists():
            resolved.append(path)
    return resolved


def _load_proverb_candidates(card_config: dict[str, Any] | None = None) -> list[str]:
    config = card_config or _load_card_config()
    configured = [
        str(item).strip()
        for item in config.get("proverbs", [])
        if isinstance(item, str) and item.strip()
    ]
    return configured or list(DEFAULT_PROVERBS)


def _choose_background_image(seed_text: str, card_config: dict[str, Any] | None = None) -> Path | None:
    del seed_text
    candidates = _load_background_candidates(card_config)
    if not candidates:
        return None
    # Pure random by design; repeated picks are allowed.
    return random.choice(candidates)


def _choose_proverb(card_config: dict[str, Any] | None = None) -> str:
    candidates = _load_proverb_candidates(card_config)
    return random.choice(candidates)


def _resize_cover(image: Any, size: tuple[int, int], Image: Any) -> Any:
    target_width, target_height = size
    src_width, src_height = image.size
    scale = max(target_width / src_width, target_height / src_height)

    if hasattr(Image, "Resampling"):
        resample = Image.Resampling.LANCZOS
    else:
        resample = Image.LANCZOS

    resized = image.resize(
        (max(1, int(src_width * scale)), max(1, int(src_height * scale))),
        resample=resample,
    )
    left = max(0, (resized.size[0] - target_width) // 2)
    top = max(0, (resized.size[1] - target_height) // 2)
    return resized.crop((left, top, left + target_width, top + target_height))


def _font(image_font_module: Any, size: int, *, bold: bool = False) -> Any:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return image_font_module.truetype(path, size=size)
        except Exception:
            continue
    return image_font_module.load_default()


def _wrap_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _short_text(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "..."
