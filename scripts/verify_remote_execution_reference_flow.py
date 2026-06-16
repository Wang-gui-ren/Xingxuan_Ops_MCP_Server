from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.approvals import ApprovalStore  # noqa: E402
from mcp_ops_server.approvals import build_approval_scope_hash  # noqa: E402
from mcp_ops_server.audit import AuditLogger  # noqa: E402
from mcp_ops_server.execution import ExecutionPolicy, ExecutionProxy  # noqa: E402
from mcp_ops_server.execution.agents.contracts import (  # noqa: E402
    build_remote_consumed_execution_agent_request,
    validate_remote_adapter_consume_request,
    validate_remote_adapter_execute_request_preview,
    validate_remote_adapter_execute_schema,
    validate_remote_consumed_execution_agent_request,
    validate_remote_reference_bundle,
    validate_remote_reference_request_contract,
)
from mcp_ops_server.tool_groups import register_approval_tools, register_execution_tools  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_remote_write_ref_") as tmp:
        root = Path(tmp)
        audit_logger = AuditLogger(root / "audit")
        approval_store = ApprovalStore(root / "approvals")
        execution_policy = ExecutionPolicy()
        proxy = ExecutionProxy()
        mcp = FakeMCP()
        register_execution_tools(
            mcp,
            proxy=proxy,
            audit_logger=audit_logger,
            approval_store=approval_store,
            execution_policy=execution_policy,
        )
        register_approval_tools(mcp, approval_store=approval_store, audit_logger=audit_logger)

        cases = [
            (
                "remote_restart_service_reference_dry_run",
                "request_restart_service",
                {
                    "service": "nginx",
                    "target": "linux-prod-01",
                    "platform_hint": "linux",
                    "remote_username": "ops",
                    "remote_port": 22,
                    "dry_run": True,
                    "reason": "verify remote reference restart",
                },
                "restart_service",
            ),
            (
                "remote_restart_service_reference_dry_run_windows",
                "request_restart_service",
                {
                    "service": "Spooler",
                    "target": "win-prod-01",
                    "platform_hint": "windows",
                    "remote_username": "admin",
                    "remote_port": 5985,
                    "remote_endpoint": "Microsoft.PowerShell",
                    "dry_run": True,
                    "reason": "verify remote windows reference restart",
                },
                "restart_service",
            ),
            (
                "remote_network_policy_reference_dry_run",
                "request_network_policy_change",
                {
                    "action": "allow",
                    "protocol": "tcp",
                    "port": 8080,
                    "target": "win-prod-01",
                    "platform_hint": "windows",
                    "dry_run": True,
                    "reason": "verify remote reference network plan",
                },
                "network_policy_change",
            ),
        ]

        for name, tool_name, params, expected_action in cases:
            result = mcp.tools[tool_name](**params)
            check(checks, result.get("ok") is True, f"{name}: dry-run returns ok")
            check(checks, result.get("risk_level") == "high", f"{name}: risk high")
            data = result.get("data", {})
            check(checks, data.get("dry_run") is True, f"{name}: dry_run true")
            check(checks, data.get("status") == "planned", f"{name}: planned status")
            check(checks, data.get("action") == expected_action, f"{name}: action recorded")
            remote_execution = data.get("remote_execution", {}) if isinstance(data.get("remote_execution"), dict) else {}
            check(checks, remote_execution.get("mode") == "reference_only", f"{name}: remote reference mode")
            check(checks, remote_execution.get("can_execute_now") is False, f"{name}: can_execute_now false")
            check(checks, remote_execution.get("structured_request_only") is True, f"{name}: structured_request_only true")
            check(checks, remote_execution.get("transport") in {"ssh", "winrm"}, f"{name}: transport captured")
            check(checks, remote_execution.get("profile_id"), f"{name}: profile_id exists")
            check(checks, isinstance(remote_execution.get("reference_request"), dict), f"{name}: reference_request exists")
            check(checks, isinstance(remote_execution.get("reference_preflight"), dict), f"{name}: reference_preflight exists")
            check(checks, isinstance(remote_execution.get("connection"), dict), f"{name}: connection plan exists")
            check(checks, isinstance(remote_execution.get("auth_requirements"), list), f"{name}: auth requirements exist")
            check(checks, isinstance(remote_execution.get("approval_binding"), dict), f"{name}: approval_binding exists")
            check(checks, isinstance(remote_execution.get("trace_binding"), dict), f"{name}: trace_binding exists")
            check(checks, isinstance(remote_execution.get("execution_contract"), dict), f"{name}: execution_contract exists")
            check(checks, isinstance(remote_execution.get("post_check_plan"), list), f"{name}: post_check_plan exists")
            check(checks, isinstance(remote_execution.get("rollback_plan"), list), f"{name}: rollback_plan exists")
            validation = remote_execution.get("bundle_validation", {})
            check(checks, isinstance(validation, dict), f"{name}: bundle_validation exists")
            check(checks, validation.get("ok") is True, f"{name}: bundle_validation ok")
            check(checks, validation.get("request_contract_ok") is True, f"{name}: bundle_validation request_contract_ok")
            check(checks, validation.get("execute_request_preview_ok") is True, f"{name}: bundle_validation execute_request_preview_ok")
            check(checks, validation.get("execute_schema_ok") is True, f"{name}: bundle_validation execute_schema_ok")
            check(checks, validation.get("consume_request_ok") is True, f"{name}: bundle_validation consume_request_ok")
            check(checks, validation.get("consumed_execution_agent_request_ok") is True, f"{name}: bundle_validation consumed_execution_agent_request_ok")
            bundle_ok, bundle_errors = validate_remote_reference_bundle(remote_execution)
            check(checks, bundle_ok is True and not bundle_errors, f"{name}: validate_remote_reference_bundle passes")
            request_contract = remote_execution.get("reference_request", {})
            request_ok, request_errors = validate_remote_reference_request_contract(
                request_contract,
                transport=str(remote_execution.get("transport") or ""),
            )
            check(checks, request_ok is True and not request_errors, f"{name}: validate_remote_reference_request_contract passes")
            execute_preview = remote_execution.get("execute_request_preview", {})
            check(checks, isinstance(execute_preview, dict), f"{name}: execute_request_preview exists")
            execute_ok, execute_errors = validate_remote_adapter_execute_request_preview(execute_preview)
            check(checks, execute_ok is True and not execute_errors, f"{name}: validate_remote_adapter_execute_request_preview passes")
            execute_schema = remote_execution.get("execute_schema", {})
            check(checks, isinstance(execute_schema, dict), f"{name}: execute_schema exists")
            schema_ok, schema_errors = validate_remote_adapter_execute_schema(execute_schema)
            check(checks, schema_ok is True and not schema_errors, f"{name}: validate_remote_adapter_execute_schema passes")
            consume_request = remote_execution.get("consume_request", {})
            check(checks, isinstance(consume_request, dict), f"{name}: consume_request exists")
            consume_ok, consume_errors = validate_remote_adapter_consume_request(consume_request)
            check(checks, consume_ok is True and not consume_errors, f"{name}: validate_remote_adapter_consume_request passes")
            consumed_execution_agent_request = build_remote_consumed_execution_agent_request(consume_request)
            check(checks, isinstance(consumed_execution_agent_request, dict), f"{name}: consumed_execution_agent_request exists")
            consumed_ok, consumed_errors = validate_remote_consumed_execution_agent_request(consumed_execution_agent_request)
            check(checks, consumed_ok is True and not consumed_errors, f"{name}: validate_remote_consumed_execution_agent_request passes")
            parameter_materialization = execute_preview.get("parameter_materialization", {}) if isinstance(execute_preview, dict) else {}
            check(checks, isinstance(parameter_materialization, dict), f"{name}: parameter_materialization exists")
            check(checks, parameter_materialization.get("mode") == "approval_bound_execute_after_reference", f"{name}: parameter_materialization mode")
            check(checks, parameter_materialization.get("parameter_values_in_summary") is False, f"{name}: parameter values stay out of summary")
            check(checks, parameter_materialization.get("parameter_values_source") == "execute_after_approval.params", f"{name}: parameter values source captured")
            check(checks, isinstance(data.get("approval_request"), dict), f"{name}: approval_request exists")
            check(checks, isinstance(data.get("execute_after_approval"), dict), f"{name}: execute_after_approval exists")
            check(checks, isinstance(data.get("human_report"), dict), f"{name}: human_report exists")
            approval_request = data.get("approval_request", {})
            approval_scope_hash = data.get("approval_scope_hash")
            if isinstance(approval_request, dict) and isinstance(approval_request.get("params"), dict):
                expected_scope_hash = build_approval_scope_hash(
                    approval_request.get("tool_name") or tool_name,
                    approval_request.get("operation") or expected_action,
                    approval_request.get("target") or params.get("target") or "local",
                    approval_request.get("params") or {},
                )
                check(checks, approval_scope_hash == expected_scope_hash, f"{name}: approval_scope_hash matches approval params")
                approval_binding = remote_execution.get("approval_binding", {})
                trace_binding = remote_execution.get("trace_binding", {})
                reference_request = remote_execution.get("reference_request", {})
                check(checks, approval_binding.get("scope_hash") == approval_scope_hash, f"{name}: approval_binding scope_hash synced")
                check(checks, approval_binding.get("approval_id_present") is False, f"{name}: approval_binding approval_id absent for dry-run")
                check(checks, trace_binding.get("trace_id") == approval_request.get("trace_id"), f"{name}: trace_binding trace_id synced")
                check(checks, trace_binding.get("session_id") == approval_request.get("session_id"), f"{name}: trace_binding session_id synced")
                check(checks, reference_request.get("scope_hash") == approval_scope_hash, f"{name}: reference_request scope_hash synced")
                check(checks, reference_request.get("trace_id") == approval_request.get("trace_id"), f"{name}: reference_request trace_id synced")
                check(checks, reference_request.get("session_id") == approval_request.get("session_id"), f"{name}: reference_request session_id synced")
            if name == "remote_restart_service_reference_dry_run":
                connection = remote_execution.get("connection", {})
                check(checks, connection.get("username") == "ops", f"{name}: remote username captured")
                check(checks, connection.get("port") == 22, f"{name}: remote port captured")
                check(checks, remote_execution.get("execution_contract", {}).get("adapter_kind") == "ssh", f"{name}: execution_contract adapter_kind ssh")
                check(checks, remote_execution.get("execution_contract", {}).get("real_execution_enabled") is False, f"{name}: execution_contract real_execution disabled")
                check(checks, remote_execution.get("approval_binding", {}).get("required_for_real_execution") is True, f"{name}: approval binding required")
                check(checks, remote_execution.get("trace_binding", {}).get("required_for_remote_audit") is True, f"{name}: trace binding required")
                request_payload = remote_execution.get("reference_request", {})
                check(checks, request_payload.get("identity_source") == "ssh_remote_username_or_host_mapping", f"{name}: identity source captured")
                check(checks, request_payload.get("endpoint_profile") == "linux-ssh-reference-v1", f"{name}: endpoint profile captured")
                check(checks, request_payload.get("host_verification_policy") == "known_hosts_strict", f"{name}: host verification policy captured")
                check(checks, isinstance(request_payload.get("health_probe_contract"), dict), f"{name}: health probe contract exists")
                check(checks, isinstance(request_payload.get("post_check_contract"), list), f"{name}: post_check_contract exists")
                check(checks, isinstance(request_payload.get("rollback_contract"), list), f"{name}: rollback_contract exists")
            if name == "remote_restart_service_reference_dry_run_windows":
                connection = remote_execution.get("connection", {})
                check(checks, connection.get("username") == "admin", f"{name}: remote username captured")
                check(checks, connection.get("port") == 5985, f"{name}: remote port captured")
                check(checks, connection.get("endpoint") == "Microsoft.PowerShell", f"{name}: remote endpoint captured")
                check(checks, remote_execution.get("execution_contract", {}).get("adapter_kind") == "winrm", f"{name}: execution_contract adapter_kind winrm")
                request_payload = remote_execution.get("reference_request", {})
                check(checks, request_payload.get("identity_source") == "winrm_remote_username_or_endpoint_mapping", f"{name}: identity source captured")
                check(checks, request_payload.get("endpoint_profile") == "Microsoft.PowerShell", f"{name}: endpoint profile captured")
                check(checks, request_payload.get("host_verification_policy") == "winrm_listener_and_tls_policy", f"{name}: host verification policy captured")

        blocked = mcp.tools["request_restart_service"](
            service="nginx",
            target="linux-prod-01",
            platform_hint="linux",
            dry_run=False,
            approval_id="appr_fake_not_found",
            reason="verify remote real execution still blocked",
        )
        check(checks, blocked.get("ok") is False, "remote real execution is blocked")
        check(
            checks,
            (
                blocked.get("data", {}).get("approval_validation", {}).get("ok") is False
                or blocked.get("data", {}).get("execution_validation", {}).get("ok") is False
                or blocked.get("data", {}).get("status") == "remote_execution_not_supported"
            ),
            "remote real execution block is explicit",
        )

        remote_dry_run = mcp.tools["request_restart_service"](
            service="nginx",
            target="linux-prod-01",
            platform_hint="linux",
            dry_run=True,
            reason="verify remote approval and execution validation chain",
            session_id="remote-reference-session",
            trace_id="remote-reference-trace",
        )
        approval_request = remote_dry_run.get("data", {}).get("approval_request", {})
        approval_payload = dict(approval_request or {})
        approval_payload["requester"] = "verify-script"
        approval_payload["expires_in_minutes"] = 30
        approval_result = mcp.tools["request_operation_approval_tool"](**approval_payload)
        approval_id = approval_result.get("data", {}).get("approval_id")
        check(checks, isinstance(approval_id, str) and approval_id.startswith("appr_"), "remote reference approval request created")

        grant_result = mcp.tools["record_operation_approval_tool"](
            approval_id=approval_id,
            decision="grant",
            approver="verify-admin",
            comment="remote reference execution validation test",
        )
        check(checks, grant_result.get("data", {}).get("approval", {}).get("status") == "granted", "remote reference approval granted")

        approved_consume_request = dict(remote_dry_run.get("data", {}).get("remote_execution", {}).get("consume_request", {}))
        if isinstance(approved_consume_request, dict):
            approved_consume_request["approval_id"] = approval_id
            approved_consumed_execution_agent_request = build_remote_consumed_execution_agent_request(approved_consume_request)
            approved_consumed_ok, approved_consumed_errors = validate_remote_consumed_execution_agent_request(approved_consumed_execution_agent_request)
            check(checks, approved_consumed_ok is True and not approved_consumed_errors, "approved consumed_execution_agent_request passes")

        execute_after = remote_dry_run.get("data", {}).get("execute_after_approval", {})
        execute_params = dict(execute_after.get("params") or {})
        execute_params["approval_id"] = approval_id
        remote_execute = mcp.tools["request_restart_service"](**execute_params)
        check(checks, remote_execute.get("ok") is False, "remote reference real execution still blocked after approval")
        execution_validation = remote_execute.get("data", {}).get("execution_validation", {})
        check(checks, isinstance(execution_validation, dict), "remote reference execution_validation exists")
        check(
            checks,
            execution_validation.get("ok") is False,
            "remote reference execution_validation blocks remote real execution",
        )
        check(
            checks,
            "remote_target_not_supported" in json.dumps(execution_validation, ensure_ascii=False)
            or remote_execute.get("data", {}).get("blocked") is True,
            "remote reference execution_validation exposes remote target boundary",
        )
        human_report = remote_dry_run.get("data", {}).get("human_report", {})
        check(
            checks,
            isinstance(human_report.get("details", {}).get("remote_execution"), dict),
            "remote reference human_report includes remote_execution details",
        )

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


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
