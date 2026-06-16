from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_ops_server.audit import (
    AuditEvent,
    AuditLogger,
    create_audit_anchor,
    ensure_audit_index,
    rebuild_audit_index,
    rotate_audit_logs,
    search_audit_events,
    sync_audit_anchor,
    verify_audit_anchor,
    verify_audit_chain,
)
from mcp_ops_server.branding import get_prefixed_env
from mcp_ops_server.guardrails import ExternalGuardContext, OperationContext, validate_intent
from mcp_ops_server.models import ToolEnvelope
from mcp_ops_server.presentation import (
    attach_human_report,
    build_audit_events_report,
    build_audit_verification_report,
    build_guardrail_report,
    build_human_report,
)
from mcp_ops_server.tracing import build_trace_context


def register_audit_tools(mcp: FastMCP, audit_logger: AuditLogger | None = None) -> None:
    """Register safety preflight, audit query and audit productionization tools."""

    audit_logger = audit_logger or AuditLogger()

    @mcp.tool()
    def validate_operation_intent_tool(
        tool_name: str,
        operation: str,
        user_intent: str | None = None,
        target: str = "local",
        platform_hint: str = "auto",
        params: dict[str, Any] | None = None,
        command: str | None = None,
        path: str | None = None,
        dry_run: bool = True,
        approval_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        guard_context: dict[str, Any] | None = None,
    ) -> dict:
        trace = build_trace_context(session_id=session_id, trace_id=trace_id)
        context = OperationContext(
            tool_name=tool_name,
            operation=operation,
            user_intent=user_intent,
            target=target,
            platform_hint=platform_hint,
            params=params or {},
            command=command,
            path=path,
            dry_run=dry_run,
            approval_id=approval_id,
            session_id=trace.session_id,
            trace_id=trace.trace_id,
            external_guard=ExternalGuardContext.from_dict(guard_context),
        )
        decision = validate_intent(context)
        audit_logger.append(
            AuditEvent(
                event_type="guardrail_decision",
                tool_name=tool_name,
                session_id=context.session_id,
                trace_id=context.trace_id,
                risk_level=decision.risk_level,
                decision=decision.decision,
                params_summary=context.to_dict(),
                result_summary=decision.to_dict(),
            )
        )
        result = ToolEnvelope(
            ok=decision.allowed,
            risk_level=decision.risk_level,
            summary=decision.summary,
            data={"decision": decision.to_dict(), "context": context.to_dict(), "trace": trace.to_dict()},
            next_actions=decision.safe_alternatives,
        ).model_dump()
        return attach_human_report(
            result,
            build_guardrail_report(
                tool_name=tool_name,
                operation=operation,
                decision=decision.to_dict(),
                context=context.to_dict(),
                trace=trace.to_dict(),
            ),
        )

    @mcp.tool()
    def get_audit_events_tool(
        limit: int = 20,
        event_type: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        events = audit_logger.read_recent(
            limit=limit,
            event_type=event_type,
            tool_name=tool_name,
            risk_level=risk_level,
            session_id=session_id,
            trace_id=trace_id,
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary=f"Loaded {len(events)} audit event(s).",
            data={"events": events, "limit": limit},
        ).model_dump()
        return attach_human_report(result, build_audit_events_report(events, limit, trace_id=trace_id))

    @mcp.tool()
    def verify_audit_chain_tool(audit_file: str | None = None) -> dict:
        """Verify one audit JSONL hash-chain segment."""

        path = audit_logger._path_for_today() if audit_file is None else Path(audit_file)
        verification = verify_audit_chain(path)
        result = ToolEnvelope(
            ok=verification.ok,
            risk_level="low" if verification.ok else "high",
            summary=verification.summary,
            data={"verification": verification.to_dict()},
            next_actions=[] if verification.ok else ["Inspect the audit JSONL for manual edits, truncation or inserted lines."],
        ).model_dump()
        return attach_human_report(result, build_audit_verification_report("Audit Hash Chain Verification", result))

    @mcp.tool()
    def anchor_audit_chain_tool(
        audit_file: str | None = None,
        signer: str = "xingxuan-mcp-local",
        transparency_log_hint: str = "local-jsonl-anchor",
    ) -> dict:
        """Create a local anchor for one audit JSONL hash-chain segment."""

        path = audit_logger._path_for_today() if audit_file is None else Path(audit_file)
        try:
            anchor = create_audit_anchor(
                path,
                signer=signer,
                transparency_log_hint=transparency_log_hint,
            )
            signature_enabled = anchor.signature_algorithm != "unsigned"
            result = ToolEnvelope(
                ok=True,
                risk_level="low",
                summary="Audit chain anchor created.",
                data={
                    "anchor": anchor.to_dict(),
                    "signature_enabled": signature_enabled,
                    "anchor_model": "local-jsonl-anchor",
                },
                next_actions=[
                    "Call verify_audit_anchor_tool to verify that the audit file still matches the anchor.",
                    "In production, configure XINGXUAN_MCP_AUDIT_ANCHOR_SECRET or sync anchors to a transparency service.",
                ],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Audit Anchor Created",
                    conclusion=result["summary"],
                    risk_level="low",
                    evidence=[
                        f"anchor_id={anchor.anchor_id}",
                        f"checked_events={anchor.checked_events}",
                        f"signature_algorithm={anchor.signature_algorithm}",
                    ],
                    risk_explanation="The anchor records a point-in-time chain head and file digest for tamper detection.",
                    safe_next_steps=result["next_actions"],
                    audit_hint="Use verify_audit_anchor_tool to compare the current file with the saved anchor.",
                    details={"anchor_model": "local-jsonl-anchor", "signature_enabled": signature_enabled},
                ),
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Failed to create audit chain anchor.",
                data={"audit_file": str(path), "error": str(exc)},
            ).model_dump()

    @mcp.tool()
    def verify_audit_anchor_tool(audit_file: str | None = None) -> dict:
        """Verify that an audit JSONL segment still matches its latest anchor."""

        path = audit_logger._path_for_today() if audit_file is None else Path(audit_file)
        verification = verify_audit_anchor(path)
        result = ToolEnvelope(
            ok=verification.ok,
            risk_level="low" if verification.ok else "high",
            summary=verification.summary,
            data={"verification": verification.to_dict()},
            next_actions=[] if verification.ok else ["Check whether the audit file, anchor file or HMAC secret changed."],
        ).model_dump()
        return attach_human_report(result, build_audit_verification_report("Audit Anchor Verification", result))

    @mcp.tool()
    def rotate_audit_logs_tool(
        force: bool = False,
        dry_run: bool = True,
        create_anchor: bool = True,
    ) -> dict:
        """Plan or execute audit log rotation and write an audit manifest."""

        rotation = rotate_audit_logs(audit_logger.audit_dir, force=force, dry_run=dry_run)
        anchor_sync = None
        if rotation.rotated and not dry_run and create_anchor and rotation.current_file:
            anchor_sync = sync_audit_anchor(
                Path(rotation.current_file),
                signer="tmp_MCP-rotation",
                transparency_log_hint="rotation-anchor",
                audit_logger=audit_logger,
            ).to_dict()
        result = ToolEnvelope(
            ok=True,
            risk_level="medium" if rotation.rotated and not dry_run else "low",
            summary=rotation.reason,
            data={"rotation": rotation.to_dict(), "anchor_sync": anchor_sync},
            next_actions=[
                "Run verify_audit_chain_tool on each manifest segment after rotation.",
                "Rebuild the audit query index if the query status reports missing files.",
            ],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Audit Rotation",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                ok=True,
                evidence=[
                    f"rotated={rotation.rotated}",
                    f"dry_run={rotation.dry_run}",
                    f"current_file={rotation.current_file}",
                    f"target_file={rotation.target_file}",
                    f"manifest_file={rotation.manifest_file}",
                ],
                risk_explanation="Rotation only changes the active write segment; old JSONL segments remain immutable evidence.",
                safe_next_steps=result["next_actions"],
                details=result["data"],
            ),
        )

    @mcp.tool()
    def get_audit_query_status_tool(rebuild_index: bool = False) -> dict:
        """Return SQLite audit index status, optionally rebuilding it."""

        status = (
            rebuild_audit_index(audit_logger.audit_dir)
            if rebuild_index
            else ensure_audit_index(audit_logger.audit_dir)
        )
        data = {"status": status.to_dict(), "rebuild_index": rebuild_index}
        ok = not status.errors
        result = ToolEnvelope(
            ok=ok,
            risk_level="low" if ok else "medium",
            summary=(
                f"Audit index tracks {status.indexed_events} event(s) from {status.indexed_files} file(s)."
                if ok
                else "Audit index status has errors."
            ),
            data=data,
            next_actions=[] if ok else ["Rebuild the audit index and inspect the reported SQLite error."],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Audit Query Status",
                conclusion=result["summary"],
                risk_level=result["risk_level"],
                ok=ok,
                evidence=[
                    f"index_file={status.index_file}",
                    f"indexed_files={status.indexed_files}",
                    f"indexed_events={status.indexed_events}",
                    f"missing_files={len(status.missing_files)}",
                ],
                risk_explanation="The SQLite index is a read-only query cache and can be rebuilt from JSONL evidence.",
                safe_next_steps=result["next_actions"],
                details=data,
            ),
        )

    @mcp.tool()
    def search_audit_events_tool(
        trace_id: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        approval_id: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """Search audit events across rotated JSONL files through the SQLite index."""

        search = search_audit_events(
            audit_logger.audit_dir,
            trace_id=trace_id,
            session_id=session_id,
            event_type=event_type,
            tool_name=tool_name,
            risk_level=risk_level,
            approval_id=approval_id,
            time_from=time_from,
            time_to=time_to,
            limit=limit,
            cursor=cursor,
        )
        result = ToolEnvelope(
            ok=True,
            risk_level="low",
            summary=f"Found {len(search.events)} audit event(s).",
            data={"search": search.to_dict()},
            next_actions=["Use next_cursor for pagination when present."],
        ).model_dump()
        return attach_human_report(
            result,
            build_human_report(
                title="Audit Search",
                conclusion=result["summary"],
                risk_level="low",
                evidence=[
                    f"events={len(search.events)}",
                    f"limit={search.limit}",
                    f"next_cursor={search.next_cursor}",
                    f"index_file={search.index_file}",
                ],
                risk_explanation="Search is read-only; original JSONL files remain the source of truth.",
                safe_next_steps=result["next_actions"],
                trace_id=trace_id,
                session_id=session_id,
                details=result["data"],
            ),
        )

    @mcp.tool()
    def sync_audit_anchor_tool(
        audit_file: str | None = None,
        signer: str = "xingxuan-mcp-local",
        transparency_log_hint: str = "local-jsonl-anchor",
    ) -> dict:
        """Create a local anchor and sync it to the configured HTTP anchor sink if present."""

        path = audit_logger._path_for_today() if audit_file is None else Path(audit_file)
        try:
            sync = sync_audit_anchor(
                path,
                signer=signer,
                transparency_log_hint=transparency_log_hint,
                audit_logger=audit_logger,
            )
            data = {"anchor_sync": sync.to_dict()}
            result = ToolEnvelope(
                ok=sync.ok,
                risk_level="low" if sync.ok else "medium",
                summary="Audit anchor synced." if sync.ok else "Audit anchor was written locally, but one or more sinks failed.",
                data=data,
                next_actions=[] if sync.ok else [f"Check {(get_prefixed_env('TMP_MCP_AUDIT_ANCHOR_HTTP_URL') or 'XINGXUAN_MCP_AUDIT_ANCHOR_HTTP_URL')} connectivity and retry sync_audit_anchor_tool."],
            ).model_dump()
            return attach_human_report(
                result,
                build_human_report(
                    title="Audit Anchor Sync",
                    conclusion=result["summary"],
                    risk_level=result["risk_level"],
                    ok=sync.ok,
                    evidence=[
                        f"anchor_id={sync.anchor.anchor_id}",
                        f"sink_count={len(sync.sink_results)}",
                        f"ok={sync.ok}",
                    ],
                    risk_explanation="Only the anchor digest is synced; complete audit events stay local.",
                    safe_next_steps=result["next_actions"],
                    details=data,
                ),
            )
        except Exception as exc:
            return ToolEnvelope(
                ok=False,
                risk_level="high",
                summary="Audit anchor sync failed before a local anchor could be created.",
                data={"audit_file": str(path), "error": str(exc)},
                next_actions=["Verify the audit file exists and its hash chain is valid."],
            ).model_dump()
