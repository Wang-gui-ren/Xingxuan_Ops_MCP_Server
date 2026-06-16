from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.audit import AuditEvent, AuditLogger
from mcp_ops_server.branding import WEB_GATEWAY_NAME
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.presentation import attach_human_report, build_human_report
from mcp_ops_server.tracing import build_trace_context
from mcp_ops_server.web.gateway_launcher import ensure_hosted_gateway


def register_gateway_tools(mcp: FastMCP, audit_logger: AuditLogger | None = None) -> None:
    """Register tools that help AstrBot open the hosted B/S gateway."""

    audit_logger = audit_logger or AuditLogger()

    @mcp.tool()
    def open_approval_console_tool(
        approval_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        host: str | None = None,
        port: int | None = None,
        options_file: str | None = None,
        allow_port_fallback: bool = True,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        """Start or reuse the hosted B/S approval console and return its URL.

        This is intended for AstrBot slash-command style integration, for
        example mapping `/approvals` to this MCP tool. It only opens the console
        surface; approval decisions and config writes still require the hosted
        gateway's existing token and identity checks.
        """

        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        launch = ensure_hosted_gateway(
            host=host,
            port=port,
            page="approvals",
            approval_id=approval_id,
            status=status,
            limit=limit,
            options_file=options_file,
            allow_port_fallback=allow_port_fallback,
        )
        launch_data = launch.to_dict()
        audit_logger.append(
            AuditEvent(
                event_type="approval_console_gateway_opened" if launch.ok else "approval_console_gateway_open_failed",
                tool_name="open_approval_console_tool",
                session_id=trace.session_id,
                trace_id=trace.trace_id,
                risk_level="low" if launch.ok else "medium",
                decision="opened" if launch.ok else "failed",
                params_summary={
                    "approval_id": approval_id,
                    "status": status,
                    "limit": limit,
                    "host": launch.host,
                    "port": launch.port,
                    "allow_port_fallback": allow_port_fallback,
                },
                result_summary={
                    "ok": launch.ok,
                    "started": launch.started,
                    "reused_existing": launch.reused_existing,
                    "page_url": launch.page_url,
                    "warnings": list(launch.warnings),
                    "error": launch.error,
                },
                error=launch.error,
            )
        )

        # Check if there are any logged-in approvers
        login_check = _check_login_status(launch.page_url if launch.ok else None, launch.host, launch.port)

        result = ToolEnvelope(
            ok=launch.ok,
            risk_level="low" if launch.ok else "medium",
            summary=(
                login_check["summary"]
                if launch.ok
                else "Approval console gateway could not be started."
            ),
            data={
                "approvals_url": launch.page_url if login_check["has_approvers"] else login_check["login_url"],
                "login_url": login_check["login_url"] if launch.ok else None,
                "login_required": not login_check["has_approvers"] if launch.ok else None,
                "approvers": login_check["approvers"] if launch.ok else None,
                "gateway": launch_data,
                "trace": trace.to_dict(),
            },
            next_actions=_next_actions_with_login(launch_data, login_check),
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Hosted Approval Console",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                ok=launch.ok,
                evidence=[
                    f"url={launch.page_url}",
                    f"login_url={login_check.get('login_url') if launch.ok else None}",
                    f"login_required={not login_check.get('has_approvers') if launch.ok else None}",
                    f"approvers={login_check.get('approvers') if launch.ok else None}",
                    f"started={launch.started}",
                    f"reused_existing={launch.reused_existing}",
                    f"host={launch.host}",
                    f"port={launch.port}",
                    f"options_file={launch.options_file}",
                ],
                risk_explanation=(
                    "This tool only starts or reuses the local B/S approval console. "
                    "It does not approve operations, bypass approval tokens, or write the approval ledger."
                ),
                safe_next_steps=result["next_actions"],
                trace_id=trace.trace_id,
                session_id=trace.session_id,
                audit_hint="The console open attempt was written to the audit log.",
                details={"gateway": _public_gateway_details(launch_data), "login_check": login_check if launch.ok else None},
            ),
        )


def _check_login_status(page_url: str | None, host: str, port: int) -> dict[str, Any]:
    """Check if there are any logged-in approvers via the gateway API."""
    import json as _json
    import urllib.request
    import urllib.error

    if not page_url:
        return {"has_approvers": False, "approvers": [], "login_url": None, "summary": "Gateway not available"}

    gateway_base = f"http://{host}:{port}"
    sessions_url = f"{gateway_base}/api/auth/sessions"
    login_url = f"{gateway_base}/login"

    try:
        with urllib.request.urlopen(sessions_url, timeout=3) as resp:
            data = _json.loads(resp.read().decode())
        approvers = data.get("data", {}).get("approvers", [])
    except Exception:
        # Gateway might not have the /api/auth/sessions endpoint or is not responding
        # Assume no approvers for safety
        approvers = []

    if not approvers:
        return {
            "has_approvers": False,
            "approvers": [],
            "login_url": login_url,
            "summary": f"审批台已就绪，请先在浏览器打开并登录：\n{login_url}\n\n登录后，审批台将自动可用。",
        }

    return {
        "has_approvers": True,
        "approvers": approvers,
        "login_url": login_url,
        "summary": f"审批台已就绪，请在浏览器打开：\n{page_url}\n\n当前已登录审批人：{', '.join(approvers)}",
    }


def _next_actions_with_login(launch_data: dict[str, Any], login_check: dict[str, Any]) -> list[str]:
    """Generate next actions based on launch status and login check."""
    if not launch_data.get("ok"):
        return [
            "Check whether the local port is occupied, then retry open_approval_console_tool with another port.",
            f"Run {WEB_GATEWAY_NAME} manually if the AstrBot process cannot spawn child Python processes.",
        ]

    if not login_check.get("has_approvers"):
        return [
            f"在浏览器打开登录页：{login_check.get('login_url')}",
            "注册或登录账号后，审批台将自动可用。",
            "登录后可直接访问审批台，无需再次输入 approver 和 token。",
        ]

    return [
        f"在浏览器打开审批台：{launch_data.get('page_url')}",
        f"当前已登录审批人：{', '.join(login_check.get('approvers', []))}",
        "审批台已自动填充登录身份，可直接操作。",
        "Map AstrBot /approvals to open_approval_console_tool if slash-command routing is available.",
    ]


def _next_actions(launch_data: dict[str, Any]) -> list[str]:
    if not launch_data.get("ok"):
        return [
            "Check whether the local port is occupied, then retry open_approval_console_tool with another port.",
            f"Run {WEB_GATEWAY_NAME} manually if the AstrBot process cannot spawn child Python processes.",
        ]
    return [
        f"Open {launch_data.get('page_url')} in a trusted local browser.",
        "Map AstrBot /approvals to open_approval_console_tool if slash-command routing is available.",
        "Use the gateway admin token only for hosted POST actions; do not paste secrets into ordinary chat.",
    ]


def _public_gateway_details(launch_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_url": launch_data.get("page_url"),
        "health_url": launch_data.get("health_url"),
        "routes_url": launch_data.get("routes_url"),
        "started": launch_data.get("started"),
        "reused_existing": launch_data.get("reused_existing"),
        "warnings": launch_data.get("warnings") or [],
        "error": launch_data.get("error"),
    }
