from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import (  # noqa: E402
    approval_identity_required,
    create_approval_decision_token,
    create_enterprise_identity_assertion,
    enterprise_approval_token_issuer_enabled,
    verify_enterprise_identity_assertion,
)
from mcp_ops_server.audit import AuditLogger  # noqa: E402
from mcp_ops_server.config import create_config_admin_identity_assertion, load_approval_identity_config  # noqa: E402
from mcp_ops_server.tool_groups import register_config_tools  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def main() -> None:
    checks: list[dict[str, Any]] = []
    env_keys = [
        "TMP_MCP_APPROVAL_IDENTITY_CONFIG_FILE",
        "TMP_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE",
        "TMP_MCP_APPROVAL_IDENTITY_SECRET",
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY",
        "TMP_MCP_REQUIRE_APPROVAL_IDENTITY_SCOPE",
        "TMP_MCP_ENABLE_ENTERPRISE_APPROVAL_TOKEN_ISSUER",
        "TMP_MCP_ENTERPRISE_IDENTITY_ASSERTION_SECRET",
        "TMP_MCP_ENTERPRISE_IDENTITY_ALLOWED_ISSUERS",
        "TMP_MCP_ENTERPRISE_APPROVER_ROLE",
    ]
    old_env = {key: os.environ.get(key) for key in env_keys}
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_identity_config_") as tmp:
        root = Path(tmp)
        config_file = root / "approval_identity.json"
        local_file = root / "approval_identity.local.json"
        config_file.write_text(json.dumps(_initial_config(), ensure_ascii=False, indent=2), encoding="utf-8")
        for key in env_keys:
            os.environ.pop(key, None)
        os.environ["TMP_MCP_APPROVAL_IDENTITY_CONFIG_FILE"] = str(config_file)
        os.environ["TMP_MCP_APPROVAL_IDENTITY_LOCAL_CONFIG_FILE"] = str(local_file)

        try:
            mcp = FakeMCP()
            audit_logger = AuditLogger(root / "audit")
            register_config_tools(mcp, audit_logger=audit_logger)

            loaded = load_approval_identity_config()
            check(checks, loaded.require_approval_identity is False, "file config loads identity mode")
            check(checks, loaded.enterprise_identity_assertion_secret_value == "verify-config-admin-secret", "file secret is usable")

            viewed = mcp.tools["get_approval_identity_config_tool"](include_sources=True, include_audit_events=True)
            check(checks, viewed["ok"] is True, "config view succeeds")
            viewed_json = json.dumps(viewed, ensure_ascii=False)
            check(checks, "verify-config-admin-secret" not in viewed_json, "config view redacts enterprise secret")
            check(checks, "verify-approval-identity-secret" not in viewed_json, "config view redacts approval secret")
            secret_status = viewed["data"]["config"]["secret_status"]
            check(checks, secret_status["approval_identity_secret"]["fingerprint"].startswith("sha256:"), "approval secret fingerprint is returned")

            invalid_missing_secret = mcp.tools["validate_approval_identity_config_tool"](
                {
                    "identity": {"require_approval_identity": True},
                    "secrets": {"approval_identity_secret": None},
                }
            )
            check(checks, invalid_missing_secret["ok"] is False, "missing approval secret is rejected")
            check(
                checks,
                "approval identity secret not configured" in invalid_missing_secret["data"]["validation"]["errors"],
                "missing secret error is stable",
            )

            invalid_issuer = mcp.tools["validate_approval_identity_config_tool"](
                {"enterprise": {"allowed_issuers": ["bad issuer"]}}
            )
            check(checks, invalid_issuer["ok"] is False, "unsafe issuer is rejected")

            admin_assertion = create_config_admin_identity_assertion(
                admin_approver="security-admin",
                roles=["mcp_security_admin"],
                issuer="verify-config-idp",
                subject="security-admin@example.com",
                secret="verify-config-admin-secret",
            )
            denied = mcp.tools["update_approval_identity_config_tool"](
                config_patch={"identity": {"require_approval_identity": True}},
                admin_approver="security-admin",
                admin_identity_assertion=None,
                change_reason="should be denied",
            )
            check(checks, denied["ok"] is False, "config update requires admin assertion")

            update = mcp.tools["update_approval_identity_config_tool"](
                config_patch={
                    "identity": {
                        "require_approval_identity": True,
                        "require_approval_identity_scope": True,
                    },
                    "enterprise": {
                        "enable_enterprise_approval_token_issuer": True,
                        "allowed_issuers": ["verify-config-idp"],
                        "required_approver_role": "ops_approver",
                    },
                },
                admin_approver="security-admin",
                admin_identity_assertion=admin_assertion,
                change_reason="verify config update",
            )
            check(checks, update["ok"] is True, "admin config update succeeds")
            update_json = json.dumps(update, ensure_ascii=False)
            check(checks, "verify-config-admin-secret" not in update_json, "update result redacts enterprise secret")
            check(checks, "verify-approval-identity-secret" not in update_json, "update result redacts approval secret")
            check(checks, update["data"]["update"]["diff"]["change_count"] >= 2, "update returns diff summary")

            check(checks, approval_identity_required() is True, "approval identity required reads config file")
            check(checks, enterprise_approval_token_issuer_enabled() is True, "enterprise issuer enabled reads config file")
            enterprise_assertion = create_enterprise_identity_assertion(
                approval_id="appr_verify_config",
                decision="grant",
                approver="approver-a",
                issuer="verify-config-idp",
                roles=["ops_approver"],
                secret=None,
            )
            verification = verify_enterprise_identity_assertion(
                enterprise_assertion,
                approval_id="appr_verify_config",
                decision="grant",
                approver="approver-a",
            )
            check(checks, verification.ok is True, "enterprise assertion verifies with config secret")
            token = create_approval_decision_token(
                approval_id="appr_verify_config",
                decision="grant",
                approver="approver-a",
                scope_hash="sha256:test-scope",
                record_event_hash="sha256:test-event",
            )
            check(checks, token.get("signature", "").startswith("hmac-sha256:"), "approval token signs with config secret")

            rotation = mcp.tools["rotate_approval_identity_secret_tool"](
                secret_kind="approval_identity_secret",
                admin_approver="security-admin",
                admin_identity_assertion=admin_assertion,
                new_secret_value="rotated-approval-identity-secret",
                new_key_id="approval-hmac-rotated",
                change_reason="verify rotation",
            )
            check(checks, rotation["ok"] is True, "approval secret rotation succeeds")
            rotation_json = json.dumps(rotation, ensure_ascii=False)
            check(checks, "rotated-approval-identity-secret" not in rotation_json, "rotation result redacts new secret")
            check(
                checks,
                rotation["data"]["rotation"]["new_secret_status"]["fingerprint"].startswith("sha256:"),
                "rotation returns new fingerprint",
            )

            bundle = mcp.tools["get_config_admin_console_bundle_tool"](include_html=True, include_audit_events=True)
            check(checks, bundle["ok"] is True, "config admin bundle succeeds")
            config_bundle = bundle["data"]["config_bundle"]
            check(checks, config_bundle.get("schema_version") == "config-admin-console-bundle-v1", "config bundle schema is stable")
            check(checks, "星璇运维MCP Config Admin" in config_bundle.get("html", ""), "config bundle contains HTML shell")
            check(checks, "config-admin-console-state" in config_bundle.get("html", ""), "config bundle embeds state")
            bundle_json = json.dumps(config_bundle, ensure_ascii=False)
            check(checks, "rotated-approval-identity-secret" not in bundle_json, "config bundle redacts rotated secret")

            event_types = {item.get("event_type") for item in audit_logger.read_recent(limit=50)}
            check(checks, "approval_identity_config_viewed" in event_types, "config view is audited")
            check(checks, "approval_identity_config_validated" in event_types, "config validation is audited")
            check(checks, "approval_identity_config_update_denied" in event_types, "config update denial is audited")
            check(checks, "approval_identity_config_updated" in event_types, "config update is audited")
            check(checks, "approval_identity_secret_rotated" in event_types, "secret rotation is audited")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


def _initial_config() -> dict[str, Any]:
    return {
        "schema_version": "approval-identity-config-v1",
        "identity": {
            "require_approval_identity": False,
            "require_approval_identity_scope": True,
            "approval_token_ttl_minutes": 15,
        },
        "enterprise": {
            "enable_enterprise_approval_token_issuer": False,
            "allowed_issuers": ["verify-config-idp"],
            "required_approver_role": "ops_approver",
            "enterprise_assertion_ttl_minutes": 10,
        },
        "secrets": {
            "approval_identity_secret": "verify-approval-identity-secret",
            "enterprise_identity_assertion_secret": "verify-config-admin-secret",
        },
        "admin": {
            "require_admin_identity": True,
            "allowed_admin_roles": ["mcp_security_admin"],
        },
    }


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
