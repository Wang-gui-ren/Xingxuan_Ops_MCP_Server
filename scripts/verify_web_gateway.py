from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import ApprovalStore, clear_policy_cache  # noqa: E402
from mcp_ops_server.tools import register_tools  # noqa: E402
from mcp_ops_server.web.gateway import create_gateway_server  # noqa: E402
from mcp_ops_server.web.gateway_launcher import ensure_hosted_gateway, shutdown_spawned_gateways  # noqa: E402


def main() -> None:
    checks: list[dict[str, Any]] = []
    env_keys = [
        "XINGXUAN_MCP_APPROVAL_DIR",
        "XINGXUAN_MCP_AUDIT_DIR",
        "XINGXUAN_MCP_APPROVAL_POLICY_FILE",
        "XINGXUAN_MCP_APPROVAL_IDENTITY_CONFIG_FILE",
        "XINGXUAN_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE",
        "XINGXUAN_MCP_WEB_GATEWAY_CONFIG_FILE",
        "XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN",
        "XINGXUAN_MCP_GATEWAY_QUIET",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_web_gateway_") as tmp:
        root = Path(tmp)
        config_file = root / "approval_identity.json"
        local_config_file = root / "approval_identity.local.json"
        gateway_options_file = root / "web_gateway.json"
        policy_file = root / "policies.yaml"
        config_file.write_text(json.dumps(_identity_config(), ensure_ascii=False, indent=2), encoding="utf-8")
        gateway_options_file.write_text(json.dumps(_web_gateway_options(), ensure_ascii=False, indent=2), encoding="utf-8")
        policy_file.write_text(_policy_text(), encoding="utf-8")
        os.environ["XINGXUAN_MCP_APPROVAL_DIR"] = str(root / "approvals")
        os.environ["XINGXUAN_MCP_AUDIT_DIR"] = str(root / "audit")
        os.environ["XINGXUAN_MCP_APPROVAL_POLICY_FILE"] = str(policy_file)
        os.environ["XINGXUAN_MCP_APPROVAL_IDENTITY_CONFIG_FILE"] = str(config_file)
        os.environ["XINGXUAN_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE"] = str(local_config_file)
        os.environ["XINGXUAN_MCP_WEB_GATEWAY_CONFIG_FILE"] = str(gateway_options_file)
        os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"] = "verify-gateway-admin-token"
        os.environ["XINGXUAN_MCP_GATEWAY_QUIET"] = "true"
        clear_policy_cache()

        server = None
        thread = None
        try:
            approval = ApprovalStore().request_approval(
                tool_name="request_modify_file",
                operation="modify_file",
                target="local",
                params={"path": str(root / "app.conf"), "operation": "replace_text", "target": "local"},
                plan={"action": "modify_file", "path": str(root / "app.conf")},
                risk_level="high",
                requester="gateway-requester",
                reason="verify hosted B/S gateway",
                trace_id="trace-web-gateway",
                session_id="session-web-gateway",
            )
            check(checks, approval.approval_id.startswith("appr_"), "temporary approval is created")

            server = create_gateway_server(
                host="127.0.0.1",
                port=0,
                admin_token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
                options_file=str(gateway_options_file),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]
            base_url = f"http://{host}:{port}"

            health = get_json(f"{base_url}/healthz")
            check(checks, health["ok"] is True, "health endpoint is reachable")
            check(checks, health["schema_version"] == "hosted-bs-gateway-v1", "gateway schema is stable")
            check(checks, health["mutating_requests_enabled"] is True, "mutation APIs report enabled with token")
            check(
                checks,
                health["options"]["schema_version"] == "web-gateway-options-v1",
                "health exposes gateway options schema",
            )

            routes = get_json(f"{base_url}/api/routes")
            check(checks, "/api/config/update" in routes["routes"]["mutation_api"], "route index exposes config update API")
            check(checks, "/gateway-settings" in routes["routes"]["pages"], "route index exposes gateway settings page")
            check(checks, "/api/audit-production" in routes["routes"]["read_api"], "route index exposes audit production API")
            check(checks, "/api/audit/rotate" in routes["routes"]["mutation_api"], "route index exposes audit rotation API")
            check(checks, "/api/audit/sync-anchor" in routes["routes"]["mutation_api"], "route index exposes audit anchor sync API")
            check(
                checks,
                "/api/gateway/options/update" in routes["routes"]["mutation_api"],
                "route index exposes gateway options update API",
            )

            approval_html = get_text(f"{base_url}/approvals?approval_id={approval.approval_id}")
            check(checks, "星璇运维MCP Approval Console" in approval_html, "approval page serves hosted HTML")
            check(checks, "approval-console-state" in approval_html, "approval page embeds state")
            check(checks, "astrbot-like-shell" in approval_html, "approval page uses AstrBot-like shell")
            check(checks, "/gateway-settings" in approval_html, "approval page links gateway settings")
            check(checks, "grid-template-columns: minmax(0, 1fr)" in approval_html and "box-sizing: border-box" in approval_html, "approval page keeps queue search full width")
            check(checks, "grid-template-columns: repeat(4, minmax(0, 1fr))" in approval_html and "text-overflow: ellipsis" in approval_html, "approval page keeps queue filter buttons inside panel")
            check(checks, '""": "&quot;"' not in approval_html, "approval page renders valid quote escaping in script")
            check(checks, "grid-template-columns: minmax(0, 960px)" in approval_html, "approval page uses centered single-column shell")
            check(checks, "justify-content: center" in approval_html, "approval page aligns with config/gateway layout baseline")
            check(checks, "linear-gradient(135deg, var(--primary), #00a3ff)" in approval_html and 'aria-hidden="true">A</div>' in approval_html, "approval page logo matches config/gateway mark style")
            check(checks, "linear-gradient(180deg, rgba(232, 243, 255, 0.65)" in approval_html, "approval page uses config/gateway blue background wash")
            check(checks, 'data-locale="zh"' in approval_html and 'data-locale="en"' in approval_html, "approval page exposes language switch tabs")
            check(checks, "星璇运维MCP 审批台" in approval_html and "审批队列" in approval_html, "approval page defaults to Chinese copy")
            check(checks, "xingxuan_mcp_ui_locale" in approval_html and "data-i18n" in approval_html, "approval page supports locale hot switch")

            config_html = get_text(f"{base_url}/config-admin")
            check(checks, "星璇运维MCP Config Admin" in config_html, "config page serves hosted HTML")
            check(checks, "config-admin-console-state" in config_html, "config page embeds state")
            check(checks, "astrbot-like-shell" in config_html, "config page uses AstrBot-like shell")
            check(checks, 'data-design-system="semi-design"' in config_html, "config page uses Semi Design shell")
            check(checks, "@douyinfe/semi-ui" in config_html, "config page references Semi Design assets")
            check(checks, 'data-semi-component="Form"' in config_html, "config page maps actions to Semi Form")
            check(checks, "semi-input" in config_html, "config page maps inputs to Semi Input")
            check(checks, 'data-locale="zh"' in config_html and 'data-locale="en"' in config_html, "config page exposes language switch tabs")
            check(checks, "星璇运维MCP 配置管理" in config_html, "config page defaults to Chinese copy")
            check(checks, "font-size: 14px" in config_html, "config page aligns base font size with AstrBot")
            check(checks, "审计生产化" in config_html, "config page exposes audit production panel")
            check(checks, "/api/audit-production" in config_html, "config page links audit production status API")
            check(checks, "rotate_audit_logs_tool" in config_html, "config page documents audit production MCP contract")

            settings_html = get_text(f"{base_url}/gateway-settings")
            check(checks, "星璇运维MCP Gateway Settings" in settings_html, "gateway settings page serves hosted HTML")
            check(checks, "gateway-settings-state" in settings_html, "gateway settings page embeds state")
            check(checks, "default_page" in settings_html, "gateway settings page exposes option controls")
            check(checks, 'data-role="gateway-switch"' in settings_html, "gateway settings page exposes switch controls")
            check(checks, 'data-control="default_page"' in settings_html, "gateway settings page exposes segmented controls")
            check(checks, 'data-design-system="semi-design"' in settings_html, "gateway settings page uses Semi Design shell")
            check(checks, "@douyinfe/semi-ui" in settings_html, "gateway settings page references Semi Design assets")
            check(checks, 'data-semi-component="Switch"' in settings_html, "gateway settings page maps switches to Semi components")
            check(checks, 'data-semi-component="RadioGroup"' in settings_html, "gateway settings page maps segmented controls to Semi RadioGroup")
            check(checks, 'role="switch"' in settings_html, "gateway settings page exposes accessible switch roles")
            check(checks, "bindFeatureEvents();" in settings_html and "gatewaySwitchKeys" in settings_html, "gateway settings page rebinds switches after locale render")
            check(checks, "status.enabled_count" in settings_html and "已开启" in settings_html, "gateway settings page localizes feature switch count")
            check(checks, ".switch-card.semi-switch" in settings_html and "max-width: none" in settings_html, "gateway settings page overrides Semi switch card width")
            check(checks, "word-break: keep-all" in settings_html and "white-space: nowrap" in settings_html, "gateway settings page prevents vertical Chinese switch titles")
            check(checks, 'data-locale="zh"' in settings_html and 'data-locale="en"' in settings_html, "gateway settings page exposes language switch tabs")
            check(checks, "网关控制选项" in settings_html, "gateway settings page defaults to Chinese copy")
            check(checks, "font-size: 14px" in settings_html, "gateway settings page aligns base font size with AstrBot")

            options_api = get_json(f"{base_url}/api/gateway/options")
            options_state = options_api["data"]["options"]
            check(checks, options_state["effective_config"]["default_page"] == "approvals", "options API returns default page")

            approval_api = get_json(f"{base_url}/api/approval-console?approval_id={approval.approval_id}")
            console_bundle = approval_api["data"]["console_bundle"]
            check(checks, approval_api["ok"] is True, "approval console API succeeds")
            check(checks, console_bundle["schema_version"] == "approval-console-bundle-v1", "approval API bundle schema is stable")
            check(checks, "html" not in console_bundle, "approval API omits html by default")

            config_api = get_json(f"{base_url}/api/config-admin-console")
            config_bundle = config_api["data"]["config_bundle"]
            config_json = json.dumps(config_bundle, ensure_ascii=False)
            check(checks, config_api["ok"] is True, "config console API succeeds")
            check(checks, config_bundle["schema_version"] == "config-admin-console-bundle-v1", "config API bundle schema is stable")
            check(checks, "verify-enterprise-secret" not in config_json, "config API redacts enterprise secret")
            check(checks, "verify-approval-secret" not in config_json, "config API redacts approval secret")
            check(checks, "audit_status_tool" in config_json, "config API bundle includes audit production contract")

            audit_production = get_json(f"{base_url}/api/audit-production?limit=5&rebuild_index=true")
            check(checks, audit_production["ok"] is True, "audit production API succeeds")
            audit_status = audit_production["data"]["status"]["status"]
            check(checks, audit_status["index_file"], "audit production API returns index file")
            check(checks, isinstance(audit_status["indexed_events"], int), "audit production API returns indexed event count")

            denied_status, denied = post_json(
                f"{base_url}/api/config/validate",
                {"config_patch": {"identity": {"require_approval_identity": False}}},
                token=None,
            )
            check(checks, denied_status == 403, "config validation POST requires gateway token")
            check(checks, denied["ok"] is False, "denied POST returns envelope")

            allowed_status, allowed = post_json(
                f"{base_url}/api/config/validate",
                {"config_patch": {"identity": {"require_approval_identity": False}}},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, allowed_status == 200, "token authorizes config validation POST")
            check(checks, allowed["ok"] is True, "authorized config validation succeeds")

            rotate_dry_status, rotate_dry = post_json(
                f"{base_url}/api/audit/rotate",
                {"force": True, "dry_run": True, "create_anchor": False},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, rotate_dry_status == 200, "token authorizes audit rotation dry-run POST")
            check(checks, rotate_dry["ok"] is True, "audit rotation dry-run succeeds")

            anchor_status, anchor_sync = post_json(
                f"{base_url}/api/audit/sync-anchor",
                {"signer": "verify-web-gateway"},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, anchor_status == 200, "token authorizes audit anchor sync POST")
            check(checks, anchor_sync["ok"] is True, "audit anchor sync succeeds with local sink")

            settings_denied_status, settings_denied = post_json(
                f"{base_url}/api/gateway/options/validate",
                {"config_patch": {"ui": {"default_page": "config-admin"}}},
                token=None,
            )
            check(checks, settings_denied_status == 403, "gateway options validate requires admin token")
            check(checks, settings_denied["ok"] is False, "gateway options denied response is envelope")

            invalid_status, invalid_options = post_json(
                f"{base_url}/api/gateway/options/validate",
                {
                    "config_patch": {
                        "ui": {"default_page": "approvals"},
                        "features": {"enable_approval_console": False},
                    }
                },
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, invalid_status == 400, "gateway options validation rejects disabled default page")
            check(checks, invalid_options["ok"] is False, "invalid gateway options return ok=false")

            update_status, update_options = post_json(
                f"{base_url}/api/gateway/options/update",
                {"config_patch": {"ui": {"default_page": "config-admin"}}},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, update_status == 200, "gateway options update succeeds with token")
            check(checks, update_options["ok"] is True, "gateway options update returns ok=true")
            health_after_update = get_json(f"{base_url}/healthz")
            check(
                checks,
                health_after_update["options"]["effective_config"]["default_page"] == "config-admin",
                "gateway options update is applied without restart",
            )

            disable_mutation_status, disable_mutation = post_json(
                f"{base_url}/api/gateway/options/update",
                {"config_patch": {"features": {"enable_mutation_apis": False}}},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, disable_mutation_status == 200, "gateway options can disable business mutation APIs")
            check(checks, disable_mutation["ok"] is True, "mutation-disable options update succeeds")
            blocked_status, blocked = post_json(
                f"{base_url}/api/config/validate",
                {"config_patch": {"identity": {"require_approval_identity": False}}},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, blocked_status == 403, "business mutation API is blocked when option is off")
            check(checks, "disabled" in blocked["summary"], "business mutation block explains disabled option")
            reenable_status, reenable = post_json(
                f"{base_url}/api/gateway/options/update",
                {"config_patch": {"features": {"enable_mutation_apis": True}}},
                token=os.environ["XINGXUAN_MCP_GATEWAY_ADMIN_TOKEN"],
            )
            check(checks, reenable_status == 200, "gateway settings API can re-enable mutation APIs")
            check(checks, reenable["ok"] is True, "mutation re-enable options update succeeds")

            reused_launch = ensure_hosted_gateway(
                host=host,
                port=port,
                approval_id=approval.approval_id,
                limit=20,
                options_file=str(gateway_options_file),
                allow_port_fallback=False,
            )
            check(checks, reused_launch.ok is True, "MCP launcher reuses an already running gateway")
            check(checks, reused_launch.reused_existing is True, "MCP launcher reports reused_existing for active gateway")
            check(checks, reused_launch.started is False, "MCP launcher does not spawn when the gateway is already healthy")
            check(checks, reused_launch.page_url.endswith(f"/approvals?approval_id={approval.approval_id}&limit=20"), "MCP launcher returns approval-specific page URL")

            registry = LocalToolRegistry()
            register_tools(registry)  # type: ignore[arg-type]
            check(checks, "open_approval_console_tool" in registry.tools, "MCP tool registry exposes open_approval_console_tool")
            open_result = registry.tools["open_approval_console_tool"](
                approval_id=approval.approval_id,
                host=host,
                port=port,
                options_file=str(gateway_options_file),
                allow_port_fallback=False,
            )
            check(checks, open_result["ok"] is True, "open_approval_console_tool succeeds through MCP registry")
            check(checks, open_result["data"]["gateway"]["reused_existing"] is True, "open_approval_console_tool reuses active gateway")
            check(checks, open_result["data"]["approvals_url"].startswith(base_url + "/approvals"), "open_approval_console_tool returns approval console URL")
            check(checks, open_result["data"]["human_report"]["details"]["gateway"]["page_url"] == open_result["data"]["approvals_url"], "open_approval_console_tool returns AstrBot-friendly human report")

            launcher_port = free_tcp_port()
            spawned_launch = ensure_hosted_gateway(
                host="127.0.0.1",
                port=launcher_port,
                approval_id=approval.approval_id,
                options_file=str(gateway_options_file),
                startup_timeout_seconds=10,
                allow_port_fallback=False,
            )
            check(checks, spawned_launch.ok is True, "MCP launcher can spawn a hosted gateway process")
            check(checks, spawned_launch.started is True, "MCP launcher reports started for a new gateway process")
            check(checks, spawned_launch.process_id is not None, "MCP launcher returns spawned process id")
            spawned_health = get_json(spawned_launch.health_url)
            check(checks, spawned_health["service"] == "xingxuan-mcp-hosted-bs-gateway", "spawned gateway health is reachable")
            spawned_html = get_text(spawned_launch.page_url)
            check(checks, "approval-console-state" in spawned_html, "spawned gateway serves approval console page")
        finally:
            shutdown_spawned_gateways()
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            clear_policy_cache()

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


def get_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def get_json(url: str) -> dict[str, Any]:
    return json.loads(get_text(url))


def post_json(url: str, payload: dict[str, Any], *, token: str | None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if token is not None:
        request.add_header("X-XINGXUAN-MCP-Admin-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LocalToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def _identity_config() -> dict[str, Any]:
    return {
        "schema_version": "approval-identity-config-v1",
        "identity": {
            "require_approval_identity": False,
            "require_approval_identity_scope": True,
            "approval_token_ttl_minutes": 15,
        },
        "enterprise": {
            "enable_enterprise_approval_token_issuer": False,
            "allowed_issuers": ["verify-gateway-idp"],
            "required_approver_role": "ops_approver",
            "enterprise_assertion_ttl_minutes": 10,
        },
        "secrets": {
            "approval_identity_secret": "verify-approval-secret",
            "enterprise_identity_assertion_secret": "verify-enterprise-secret",
        },
        "admin": {
            "require_admin_identity": True,
            "allowed_admin_roles": ["mcp_security_admin"],
        },
    }


def _web_gateway_options() -> dict[str, Any]:
    return {
        "schema_version": "web-gateway-options-v1",
        "ui": {
            "default_page": "approvals",
            "style": "xingxuan_mcp",
            "density": "compact",
        },
        "features": {
            "enable_approval_console": True,
            "enable_config_admin_console": True,
            "enable_read_apis": True,
            "enable_mutation_apis": True,
            "show_gateway_settings": True,
            "show_api_index": True,
        },
        "security": {
            "require_admin_token_for_mutation": True,
        },
    }


def _policy_text() -> str:
    return """
version: "web-gateway-test"
default:
  decision: allow_request
  ttl_minutes: 60
  max_renewals: 1
  required_approvals: 1
  require_distinct_approvers: true
  allow_self_approval: false
approvers:
  trusted_ids:
    - gateway-approver
rules: []
"""


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
