from __future__ import annotations

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_ops_server.audit import (  # noqa: E402
    AuditEvent,
    AuditLogger,
    AuditRotationPolicy,
    build_audit_manifest,
    list_audit_files,
    rebuild_audit_index,
    rotate_audit_logs,
    search_audit_events,
    sync_audit_anchor,
    verify_audit_chain,
)
from mcp_ops_server.tool_groups import register_audit_tools  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., dict[str, Any]]] = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


class AnchorReceiver(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        self.__class__.received.append(payload)
        response = json.dumps({"ok": True, "receipt_id": f"rcpt-{len(self.__class__.received)}"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: Any) -> None:
        return None


def main() -> None:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="tmp_mcp_audit_prod_") as tmp:
        root = Path(tmp)
        audit_dir = root / "audit"
        logger = AuditLogger(audit_dir)
        policy = AuditRotationPolicy(max_file_size_mb=64, retention_days=90)

        for index in range(4):
            logger.append(
                AuditEvent(
                    event_type="guardrail_decision",
                    tool_name="verify_audit_productionization",
                    risk_level="low",
                    decision="allow",
                    session_id="session-audit-prod",
                    trace_id="trace-audit-prod",
                    params_summary={"index": index},
                    result_summary={"approval_id": "appr_audit_prod", "phase": "before_rotate"},
                )
            )
        files_before = list_audit_files(audit_dir)
        check(checks, len(files_before) == 1, "legacy audit file is created before manual rotation")

        rotation = rotate_audit_logs(audit_dir, force=True, dry_run=False, policy=policy)
        check(checks, rotation.rotated is True and rotation.target_file, "forced rotation creates a target segment")
        check(checks, rotation.manifest_file is not None and Path(rotation.manifest_file).exists(), "rotation writes manifest")
        legacy_size = Path(rotation.current_file or "").stat().st_size

        for index in range(3):
            logger.append(
                AuditEvent(
                    event_type="tool_result",
                    tool_name="verify_audit_productionization",
                    risk_level="low",
                    decision="completed",
                    session_id="session-audit-prod",
                    trace_id="trace-audit-prod",
                    params_summary={"index": index},
                    result_summary={"approval_id": "appr_audit_prod", "phase": "after_rotate"},
                )
            )
        files_after = list_audit_files(audit_dir)
        check(checks, len(files_after) >= 2, "post-rotation events use a segmented file")
        check(checks, Path(rotation.current_file or "").stat().st_size == legacy_size, "old segment is not appended after rotation")
        for path in files_after:
            verification = verify_audit_chain(path)
            check(checks, verification.ok is True, f"hash chain verifies for {path.name}")

        manifest = build_audit_manifest(audit_dir).to_dict()
        check(checks, len(manifest["segments"]) >= 2, "manifest records multiple audit segments")
        check(checks, all(segment["head_hash"].startswith("sha256:") or segment["checked_events"] == 0 for segment in manifest["segments"]), "manifest records head hashes")

        index_file = root / "index" / "audit_index.sqlite3"
        status = rebuild_audit_index(audit_dir, index_file=index_file)
        jsonl_count = sum(1 for path in files_after for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        check(checks, status.indexed_events == jsonl_count, "SQLite index event count matches JSONL line count")
        index_file.unlink()
        rebuilt = rebuild_audit_index(audit_dir, index_file=index_file)
        check(checks, rebuilt.indexed_events == jsonl_count, "deleted SQLite index can be rebuilt")

        search = search_audit_events(audit_dir, index_file=index_file, trace_id="trace-audit-prod", limit=20)
        check(checks, len(search.events) == jsonl_count, "search returns cross-file events by trace_id")
        check(checks, all(item.get("audit_file") and item.get("line_number") for item in search.events), "search returns source file and line number")

        AnchorReceiver.received = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), AnchorReceiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            http_url = f"http://127.0.0.1:{server.server_address[1]}/anchors"
            sync_ok = sync_audit_anchor(files_after[-1], signer="verify", http_url=http_url)
            check(checks, sync_ok.ok is True, "HTTP anchor sink returns success")
            check(checks, len(AnchorReceiver.received) == 1, "HTTP anchor sink receives one anchor")
            check(checks, AnchorReceiver.received[0]["head_hash"] == sync_ok.anchor.head_hash, "HTTP receipt matches local head hash")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        failed_sync = sync_audit_anchor(
            files_after[-1],
            signer="verify",
            http_url="http://127.0.0.1:1/unavailable",
            http_timeout_seconds=0.2,
            audit_logger=logger,
        )
        check(checks, failed_sync.ok is False, "HTTP anchor sink failure is reported")
        failure_events = logger.read_recent(limit=20, event_type="audit_anchor_sync_failed")
        check(checks, bool(failure_events), "HTTP anchor failure writes an audit event")

        mcp = FakeMCP()
        register_audit_tools(mcp, audit_logger=logger)  # type: ignore[arg-type]
        for name in (
            "rotate_audit_logs_tool",
            "get_audit_query_status_tool",
            "search_audit_events_tool",
            "sync_audit_anchor_tool",
            "get_audit_events_tool",
        ):
            check(checks, name in mcp.tools, f"{name} is registered")
        check(checks, mcp.tools["rotate_audit_logs_tool"](force=True, dry_run=True)["ok"] is True, "rotation tool dry-run succeeds")
        check(checks, mcp.tools["get_audit_query_status_tool"](rebuild_index=True)["ok"] is True, "query status tool rebuild succeeds")
        search_result = mcp.tools["search_audit_events_tool"](trace_id="trace-audit-prod", limit=10)
        check(checks, search_result["ok"] is True and search_result["data"]["search"]["events"], "search tool returns indexed events")
        anchor_result = mcp.tools["sync_audit_anchor_tool"](signer="verify-script")
        check(checks, anchor_result["ok"] is True, "anchor sync tool succeeds with local sink")

    report = {
        "total": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "PASS"),
        "failed": sum(1 for item in checks if item["status"] == "FAIL"),
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"]:
        raise SystemExit(1)


def check(checks: list[dict[str, Any]], condition: bool, name: str) -> None:
    checks.append({"name": name, "status": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)


if __name__ == "__main__":
    main()
