from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.execution import (  # noqa: E402
    ExecutionPolicy,
    ExecutionAgentRequest,
    ReferenceExecutionAgentAdapter,
    get_execution_agent_profile,
    list_execution_agent_profiles,
)


def main() -> None:
    checks: list[dict[str, Any]] = []
    old_profile = os.environ.get("TMP_MCP_EXECUTION_AGENT_PROFILE")
    try:
        profiles = list_execution_agent_profiles()
        check(checks, len(profiles) >= 2, "predefined agent profiles are listed")
        linux_profile = get_execution_agent_profile("linux-kylin-ops-agent-v1")
        check(checks, linux_profile is not None, "linux kylin ops-agent profile exists")
        check(checks, linux_profile.platform == "linux", "linux profile records platform")
        check(checks, linux_profile.deployment_state == "reference_only", "linux profile is reference only")
        check(checks, linux_profile.can_execute_privileged_templates is False, "reference profile cannot execute privileged templates")
        check(checks, "TPL_SERVICE_RESTART_V1" in linux_profile.allowed_template_ids, "linux profile declares service restart template")
        check(checks, "arbitrary_shell" in linux_profile.denied_capabilities, "linux profile denies arbitrary shell")

        adapter = ReferenceExecutionAgentAdapter(linux_profile)
        structured_request = ExecutionAgentRequest(
            template_id="TPL_SERVICE_RESTART_V1",
            action="restart_service",
            platform="linux",
            target="local",
            params={"service": "nginx"},
            profile_id="linux-kylin-ops-agent-v1",
        )
        preflight = adapter.preflight(
            structured_request,
            runtime_identity=_current_user_lower(),
            trusted_identities={_current_user_lower()},
        )
        check(checks, preflight.ok is False, "reference-only adapter preflight blocks privileged execution")
        check(checks, preflight.fixed_template_only is True, "adapter preflight records fixed template boundary")
        check(checks, _has_error(preflight, "execution_agent_profile_not_deployed"), "adapter preflight reports not deployed")
        check(checks, preflight.checks.get("request", {}).get("params_keys") == ["service"], "adapter request summary only exposes params keys")

        shell_request = ExecutionAgentRequest(
            template_id="TPL_SERVICE_RESTART_V1",
            action="restart_service",
            platform="linux",
            target="local",
            params={"command": "sudo systemctl restart nginx"},
            profile_id="linux-kylin-ops-agent-v1",
        )
        shell_preflight = adapter.preflight(
            shell_request,
            runtime_identity=_current_user_lower(),
            trusted_identities={_current_user_lower()},
        )
        check(checks, _has_error(shell_preflight, "execution_agent_request_not_structured"), "adapter rejects arbitrary command fields")
        request_summary = shell_preflight.checks.get("request", {})
        check(checks, "sudo systemctl restart nginx" not in json.dumps(request_summary, ensure_ascii=False), "adapter request summary does not echo raw command")

        unknown_request = ExecutionAgentRequest(
            template_id="TPL_UNKNOWN_V1",
            action="restart_service",
            platform="linux",
            target="local",
            params={"service": "nginx"},
            profile_id="linux-kylin-ops-agent-v1",
        )
        unknown_preflight = adapter.preflight(
            unknown_request,
            runtime_identity=_current_user_lower(),
            trusted_identities={_current_user_lower()},
        )
        check(checks, _has_error(unknown_preflight, "execution_agent_template_not_found"), "adapter rejects unknown template id")

        execute_result = adapter.execute(
            structured_request,
            runtime_identity=_current_user_lower(),
            trusted_identities={_current_user_lower()},
        )
        check(checks, execute_result.ok is False and execute_result.status == "blocked", "reference adapter execute is blocked")
        check(checks, _has_error(execute_result, "execution_agent_execute_not_implemented"), "reference adapter refuses real execution")

        os.environ.pop("TMP_MCP_EXECUTION_AGENT_PROFILE", None)
        disabled_policy = ExecutionPolicy(allow_privileged_execution=False)
        disabled = _validate_restart(disabled_policy)
        check(checks, disabled.ok is False, "privileged template is blocked when global switch is disabled")
        check(checks, _has_error(disabled, "privileged_template_disabled"), "disabled switch reports stable error")

        missing_policy = ExecutionPolicy(allow_privileged_execution=True, trusted_identities={_current_user_lower()})
        missing = _validate_restart(missing_policy)
        check(checks, missing.ok is False, "privileged template is blocked without agent profile")
        check(checks, _has_error(missing, "execution_agent_profile_missing"), "missing profile reports stable error")

        os.environ["TMP_MCP_EXECUTION_AGENT_PROFILE"] = "linux-kylin-ops-agent-v1"
        reference_policy = ExecutionPolicy(allow_privileged_execution=True, trusted_identities={_current_user_lower()})
        reference = _validate_restart(reference_policy)
        check(checks, reference.ok is False, "reference-only profile still blocks real privileged execution")
        check(checks, _has_error(reference, "execution_agent_profile_not_deployed"), "reference-only profile reports not deployed")
        identity_checks = reference.checks.get("identity", {})
        agent_checks = identity_checks.get("agent_profile", {})
        profile = agent_checks.get("profile", {})
        policy_preflight = agent_checks.get("adapter_preflight", {})
        policy_request = policy_preflight.get("checks", {}).get("request", {})
        check(checks, profile.get("profile_id") == "linux-kylin-ops-agent-v1", "validation exposes selected profile")
        check(checks, profile.get("deployment_state") == "reference_only", "validation exposes deployment state")
        check(checks, policy_request.get("params_keys") == ["service"], "policy adapter preflight exposes sanitized params keys")
        check(checks, "nginx" not in json.dumps(policy_request, ensure_ascii=False), "policy adapter preflight does not expose params values")

        injected = _validate_restart(
            reference_policy,
            params={"service": "nginx", "command": "sudo systemctl restart nginx"},
        )
        injected_preflight = (
            injected.checks.get("identity", {})
            .get("agent_profile", {})
            .get("adapter_preflight", {})
        )
        injected_request = injected_preflight.get("checks", {}).get("request", {})
        check(checks, _has_error(injected, "execution_agent_request_not_structured"), "policy adapter preflight rejects command fields")
        check(checks, "params.command" in injected_request.get("denied_request_keys", []), "policy adapter preflight records denied command key")
        check(checks, "sudo systemctl restart nginx" not in json.dumps(injected_request, ensure_ascii=False), "policy adapter preflight does not echo injected command")

        os.environ["TMP_MCP_EXECUTION_AGENT_PROFILE"] = "windows-jea-endpoint-v1"
        mismatch_policy = ExecutionPolicy(allow_privileged_execution=True, trusted_identities={_current_user_lower()})
        mismatch = _validate_restart(mismatch_policy)
        check(checks, mismatch.ok is False, "platform-mismatched profile blocks real execution")
        check(checks, _has_error(mismatch, "execution_agent_profile_platform_mismatch"), "platform mismatch reports stable error")

        dry_run = _validate_restart(reference_policy, dry_run=True, approval_validation=None)
        check(checks, dry_run.ok is True, "dry-run does not require agent profile")
        check(checks, dry_run.decision == "allow_dry_run", "dry-run keeps allow_dry_run decision")
    finally:
        if old_profile is None:
            os.environ.pop("TMP_MCP_EXECUTION_AGENT_PROFILE", None)
        else:
            os.environ["TMP_MCP_EXECUTION_AGENT_PROFILE"] = old_profile

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


def _validate_restart(
    policy: ExecutionPolicy,
    *,
    params: dict[str, Any] | None = None,
    dry_run: bool = False,
    approval_validation: dict[str, Any] | None = None,
):
    return policy.validate(
        tool_name="request_restart_service",
        operation="restart_service",
        target="local",
        platform_hint="linux",
        params=params or {"service": "nginx"},
        dry_run=dry_run,
        approval_validation={"ok": True, "errors": []} if approval_validation is None and not dry_run else approval_validation,
    )


def _has_error(validation: Any, needle: str) -> bool:
    return any(needle in item for item in validation.errors)


def _current_user_lower() -> str:
    try:
        return getpass.getuser().lower()
    except Exception:  # noqa: BLE001 - 仅用于本地验证兜底。
        return "unknown"


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})


if __name__ == "__main__":
    main()
