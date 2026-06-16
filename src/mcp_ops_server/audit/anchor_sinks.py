from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_ops_server.branding import get_prefixed_env
from mcp_ops_server.audit.anchor import AuditAnchor, create_audit_anchor
from mcp_ops_server.audit.models import AuditEvent


DEFAULT_HTTP_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class AnchorSinkResult:
    sink_type: str
    ok: bool
    summary: str
    receipt: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sink_type": self.sink_type,
            "ok": self.ok,
            "summary": self.summary,
            "receipt": self.receipt,
            "error": self.error,
        }


@dataclass(frozen=True)
class AnchorSyncResult:
    anchor: AuditAnchor
    sink_results: list[AnchorSinkResult]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.sink_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "anchor": self.anchor.to_dict(),
            "sink_results": [result.to_dict() for result in self.sink_results],
        }


def sync_audit_anchor(
    audit_file: Path,
    *,
    signer: str = "xingxuan-mcp-local",
    transparency_log_hint: str = "local-jsonl-anchor",
    anchor_dir: Path | None = None,
    http_url: str | None = None,
    http_token: str | None = None,
    http_timeout_seconds: float | None = None,
    audit_logger: Any | None = None,
) -> AnchorSyncResult:
    anchor = create_audit_anchor(
        audit_file,
        anchor_dir=anchor_dir,
        signer=signer,
        transparency_log_hint=transparency_log_hint,
    )
    sink_results = [
        AnchorSinkResult(
            sink_type="local-jsonl",
            ok=True,
            summary="local anchor written",
            receipt={"anchor_id": anchor.anchor_id, "audit_file": anchor.audit_file},
        )
    ]

    url = http_url if http_url is not None else get_prefixed_env("TMP_MCP_AUDIT_ANCHOR_HTTP_URL")
    if url:
        token = http_token if http_token is not None else get_prefixed_env("TMP_MCP_AUDIT_ANCHOR_HTTP_TOKEN")
        timeout = http_timeout_seconds if http_timeout_seconds is not None else _float_env("TMP_MCP_AUDIT_ANCHOR_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS)
        http_result = _post_anchor(url, anchor.to_dict(), token=token, timeout_seconds=timeout)
        sink_results.append(http_result)
        if not http_result.ok and audit_logger is not None:
            audit_logger.append(
                AuditEvent(
                    event_type="audit_anchor_sync_failed",
                    tool_name="sync_audit_anchor_tool",
                    risk_level="medium",
                    decision="degraded",
                    params_summary={"audit_file": str(audit_file), "sink_type": "http-anchor", "anchor_id": anchor.anchor_id},
                    result_summary={"summary": http_result.summary, "error": http_result.error},
                )
            )

    return AnchorSyncResult(anchor=anchor, sink_results=sink_results)


def _post_anchor(url: str, payload: dict[str, Any], *, token: str | None, timeout_seconds: float) -> AnchorSinkResult:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                receipt: dict[str, Any] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                receipt = {"body": raw}
            receipt["status"] = response.status
            return AnchorSinkResult(
                sink_type="http-anchor",
                ok=200 <= response.status < 300,
                summary=f"http anchor sink returned {response.status}",
                receipt=receipt,
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return AnchorSinkResult(
            sink_type="http-anchor",
            ok=False,
            summary="http anchor sink failed",
            error=str(exc),
        )


def _float_env(name: str, default: float) -> float:
    value = get_prefixed_env(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default
