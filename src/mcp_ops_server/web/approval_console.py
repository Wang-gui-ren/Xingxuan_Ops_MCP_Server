from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


CONSOLE_SCHEMA_VERSION = "approval-console-bundle-v1"


def build_approval_console_bundle(
    *,
    approvals: list[dict[str, Any]],
    selected_packet: dict[str, Any] | None = None,
    audit_events: list[dict[str, Any]] | None = None,
    identity_mode: dict[str, Any] | None = None,
    include_html: bool = True,
    session_approver: str | None = None,
) -> dict[str, Any]:
    """Build an embeddable browser approval console bundle.

    The returned HTML is intentionally self-contained so AstrBot or a future
    HTTP gateway can render the page without adding a web framework to the MCP
    server process.
    """

    _ = session_approver
    normalized_approvals = [_approval_summary(item) for item in approvals]
    review_packet = selected_packet or {}
    selected_id = (
        review_packet.get("approval_id")
        or (normalized_approvals[0].get("approval_id") if normalized_approvals else None)
    )
    state = {
        "schema_version": CONSOLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": _metrics(normalized_approvals, review_packet),
        "approvals": normalized_approvals,
        "selected_approval_id": selected_id,
        "review_packet": review_packet,
        "audit_events": list(audit_events or []),
        "identity_mode": dict(identity_mode or {}),
        "mcp_contract": {
            "read_tool": "get_approval_console_bundle_tool",
            "issue_token_tool": "issue_enterprise_approval_token_tool",
            "record_tool": "record_operation_approval_tool",
            "required_token_field": "approval_token",
            "enterprise_assertion_field": "enterprise_assertion",
        },
    }
    bundle = {
        "schema_version": CONSOLE_SCHEMA_VERSION,
        "generated_at": state["generated_at"],
        "design_system": _design_system(),
        "state": state,
    }
    if include_html:
        bundle["html"] = _render_html(state)
    return bundle


def _approval_summary(approval: dict[str, Any]) -> dict[str, Any]:
    history = approval.get("approver_history") or []
    latest_identity = None
    if isinstance(history, list):
        for item in reversed(history):
            if isinstance(item, dict) and isinstance(item.get("identity"), dict):
                latest_identity = item["identity"]
                break
    return {
        "approval_id": approval.get("approval_id"),
        "status": approval.get("status"),
        "risk_level": approval.get("risk_level"),
        "tool_name": approval.get("tool_name"),
        "operation": approval.get("operation"),
        "target": approval.get("target"),
        "requester": approval.get("requester"),
        "approver": approval.get("approver"),
        "reason": approval.get("reason"),
        "scope_hash": approval.get("scope_hash"),
        "trace_id": approval.get("trace_id"),
        "session_id": approval.get("session_id"),
        "created_at": approval.get("created_at"),
        "updated_at": approval.get("updated_at"),
        "expires_at": approval.get("expires_at"),
        "required_approvals": approval.get("required_approvals"),
        "granted_approvals": approval.get("granted_approvals"),
        "policy_rule_ids": list(approval.get("policy_rule_ids") or []),
        "policy_reasons": list(approval.get("policy_reasons") or []),
        "params_summary": dict(approval.get("params_summary") or {}),
        "plan_summary": dict(approval.get("plan_summary") or {}),
        "latest_identity": latest_identity,
        "event_hash": approval.get("event_hash"),
        "prev_hash": approval.get("prev_hash"),
    }


def _metrics(approvals: list[dict[str, Any]], review_packet: dict[str, Any]) -> dict[str, Any]:
    statuses = [str(item.get("status") or "") for item in approvals]
    risks = [str(item.get("risk_level") or "") for item in approvals]
    identity = review_packet.get("identity") if isinstance(review_packet.get("identity"), dict) else {}
    audit = review_packet.get("audit") if isinstance(review_packet.get("audit"), dict) else {}
    return {
        "total": len(approvals),
        "pending": sum(1 for item in statuses if item in {"requested", "partially_granted"}),
        "granted": statuses.count("granted"),
        "rejected": statuses.count("rejected"),
        "terminal": sum(1 for item in statuses if item in {"rejected", "revoked", "expired"}),
        "high_risk": sum(1 for item in risks if item in {"high", "critical"}),
        "verified_identity_count": int(identity.get("verified_identity_count") or 0),
        "audit_event_count": int(audit.get("event_count") or 0),
    }


def _design_system() -> dict[str, Any]:
    return {
        "name": "tmp-mcp-approval-console",
        "palette": {
            "background": "#f9fafc",
            "surface": "#ffffff",
            "ink": "#111827",
            "muted": "#6b7280",
            "line": "#d0d7de",
            "primary": "#3c96ca",
            "accent": "#2f86bd",
            "success": "#00a152",
            "warning": "#b45309",
            "danger": "#dc2626",
        },
        "radius_px": 8,
        "font_stack": "Inter, Segoe UI, system-ui, sans-serif",
        "mono_stack": "Fira Code, Consolas, ui-monospace, monospace",
    }


def _render_html(state: dict[str, Any]) -> str:
    state_json = _safe_script_json(state)
    return _HTML_TEMPLATE.replace("__STATE_JSON__", state_json)


def _safe_script_json(value: dict[str, Any]) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>星璇运维MCP 审批台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f8fc;
      --surface: #ffffff;
      --sidebar: rgba(255, 255, 255, 0.94);
      --ink: #0f172a;
      --muted: #5b6b82;
      --line: #d8e4ee;
      --soft-line: #eaf1f6;
      --primary: #0f6fbf;
      --accent: #18a0c9;
      --light-primary: #e6f5fb;
      --light-secondary: #eef7ff;
      --success: #00a152;
      --warning: #b45309;
      --danger: #dc2626;
      --radius: 10px;
      --shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
      font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(24, 160, 201, 0.16), transparent 30%),
        linear-gradient(180deg, rgba(15, 111, 191, 0.08), transparent 260px),
        var(--bg);
      color: var(--ink);
    }
    button, input, textarea { font: inherit; }
    button:focus-visible, input:focus-visible, textarea:focus-visible {
      outline: 3px solid rgba(14, 165, 233, 0.35);
      outline-offset: 2px;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      position: sticky;
      top: 0;
      z-index: 3;
      backdrop-filter: blur(12px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .brand-mark {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #fff;
      font-weight: 800;
      flex: 0 0 auto;
    }
    .brand h1 {
      margin: 0;
      font-size: 17px;
      line-height: 1.1;
      letter-spacing: 0;
    }
    .brand p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .locale-switch {
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(42px, 1fr));
      padding: 2px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #f7f8fa;
    }
    .locale-switch button {
      min-height: 26px;
      border: 0;
      border-radius: 5px;
      background: transparent;
      color: var(--muted);
      padding: 3px 8px;
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 700;
    }
    .locale-switch button.active {
      background: #fff;
      color: var(--primary);
      box-shadow: 0 2px 6px rgba(31, 35, 41, 0.1);
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 5px 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .pill strong { color: var(--ink); font-weight: 700; }
    .shell {
      display: grid;
      grid-template-columns: minmax(0, 960px);
      justify-content: center;
      align-content: start;
      gap: 14px;
      padding: 14px;
      min-height: 0;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 48px;
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
    }
    .panel-head h2 {
      margin: 0;
      font-size: 13px;
      letter-spacing: 0;
    }
    .panel-body {
      min-height: 0;
      overflow: auto;
      padding: 12px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      background: #fbfdff;
      min-height: 70px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 7px;
      font-size: 24px;
      line-height: 1;
    }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      align-items: stretch;
      gap: 8px;
      margin-bottom: 10px;
    }
    .search {
      width: 100%;
      min-width: 0;
      min-height: 34px;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 6px 9px;
      color: var(--ink);
      background: #fff;
    }
    .segmented {
      width: 100%;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
      background: #fff;
    }
    .segmented button {
      min-width: 0;
      min-height: 34px;
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 0 10px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .segmented button:last-child { border-right: 0; }
    .segmented button.active {
      background: #e0f2fe;
      color: var(--primary);
      font-weight: 700;
    }
    .approval-list {
      display: grid;
      gap: 8px;
    }
    .approval-item {
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #fff;
      cursor: pointer;
      padding: 10px;
      min-height: 108px;
      display: grid;
      gap: 8px;
    }
    .approval-item.active {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
    }
    .id {
      font-family: "Fira Code", Consolas, ui-monospace, monospace;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 7px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 11px;
      color: var(--muted);
      background: #fff;
      white-space: nowrap;
    }
    .badge.requested, .badge.partially_granted { color: var(--warning); border-color: #f5d08a; background: #fffbeb; }
    .badge.granted { color: var(--success); border-color: #86efac; background: #f0fdf4; }
    .badge.rejected, .badge.revoked, .badge.expired { color: var(--danger); border-color: #fecaca; background: #fef2f2; }
    .badge.high, .badge.critical { color: var(--danger); border-color: #fecaca; background: #fff5f5; }
    .badge.medium { color: var(--warning); border-color: #f5d08a; background: #fffbeb; }
    .title {
      margin: 0;
      font-size: 13px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .subtle {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(260px, 0.8fr);
      gap: 12px;
      align-items: start;
    }
    .section {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #fff;
      padding: 12px;
      min-width: 0;
    }
    .section + .section { margin-top: 12px; }
    .section h3 {
      margin: 0 0 10px;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .kv {
      display: grid;
      grid-template-columns: 142px minmax(0, 1fr);
      gap: 7px 10px;
      font-size: 12px;
    }
    .kv dt {
      color: var(--muted);
    }
    .kv dd {
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
      font-family: "Fira Code", Consolas, ui-monospace, monospace;
    }
    .timeline {
      display: grid;
      gap: 8px;
    }
    .timeline-item {
      display: grid;
      grid-template-columns: 10px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-top: 4px;
      background: var(--accent);
    }
    .timeline-item.audit .dot { background: var(--success); }
    .timeline-copy {
      border-bottom: 1px solid #eef2f7;
      padding-bottom: 8px;
    }
    .controls {
      display: grid;
      gap: 10px;
    }
    .field {
      display: grid;
      gap: 5px;
    }
    .field label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .field input, .field textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      min-height: 34px;
      padding: 7px 9px;
      resize: vertical;
      background: #fff;
      color: var(--ink);
      font-family: "Fira Code", Consolas, ui-monospace, monospace;
      font-size: 12px;
    }
    .field textarea { min-height: 96px; }
    .button-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .btn {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 0 10px;
      white-space: nowrap;
    }
    .btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .btn.danger { color: var(--danger); border-color: #fecaca; background: #fff5f5; }
    .btn svg { width: 15px; height: 15px; flex: 0 0 auto; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font: 11px/1.45 "Fira Code", Consolas, ui-monospace, monospace;
      color: #1e293b;
      background: #f8fafc;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      max-height: 220px;
      overflow: auto;
    }
    .empty {
      border: 1px dashed var(--line);
      border-radius: var(--radius);
      padding: 18px;
      color: var(--muted);
      text-align: center;
      font-size: 13px;
    }
    .astrbot-like-shell {
      grid-template-columns: 244px minmax(0, 1fr);
      grid-template-rows: auto 1fr;
      background:
        linear-gradient(180deg, rgba(232, 243, 255, 0.65) 0, rgba(249, 250, 252, 0) 270px),
        var(--bg);
    }
    .sidebar {
      grid-column: 1;
      grid-row: 1 / 3;
      position: sticky;
      top: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      gap: 14px;
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      padding: 14px 10px;
    }
    .side-brand {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 8px 8px;
    }
    .side-brand h2 {
      margin: 0;
      font-size: 14px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .side-brand p {
      margin: 2px 0 0;
      color: var(--muted);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .nav {
      display: grid;
      gap: 4px;
    }
    .nav a {
      min-height: 40px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 10px;
      border-radius: var(--radius);
      color: #2b3540;
      text-decoration: none;
      font-size: 13px;
    }
    .nav a:hover { background: var(--light-primary); color: var(--primary); }
    .nav a.active { background: var(--light-secondary); color: var(--accent); font-weight: 700; }
    .nav svg { width: 17px; height: 17px; flex: 0 0 auto; }
    .side-footer {
      margin-top: auto;
      padding: 10px;
      border: 1px solid var(--soft-line);
      border-radius: var(--radius);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      background: #fbfdff;
    }
    .astrbot-like-shell .topbar {
      grid-column: 2;
      grid-row: 1;
    }
    .astrbot-like-shell .shell {
      grid-column: 2;
      grid-row: 2;
    }
    @media (max-width: 1180px) {
      .shell { grid-template-columns: minmax(0, 960px); }
    }
    @media (max-width: 760px) {
      .topbar { grid-template-columns: 1fr; align-items: start; }
      .top-actions { justify-content: flex-start; }
      .shell { grid-template-columns: 1fr; padding: 10px; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .detail-grid { grid-template-columns: 1fr; }
      .toolbar { grid-template-columns: minmax(0, 1fr); }
      .segmented { grid-template-columns: 1fr; }
      .segmented button { border-right: 0; border-bottom: 1px solid var(--line); }
      .segmented button:last-child { border-bottom: 0; }
      .kv { grid-template-columns: 1fr; }
    }
    @media (max-width: 1040px) {
      .astrbot-like-shell { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        grid-column: 1;
        grid-row: 1;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .side-footer { display: none; }
      .astrbot-like-shell .topbar {
        grid-column: 1;
        grid-row: 2;
      }
      .astrbot-like-shell .shell {
        grid-column: 1;
        grid-row: 3;
      }
    }
    @media (max-width: 760px) {
      .nav { grid-template-columns: 1fr; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <script type="application/json" id="approval-console-state">__STATE_JSON__</script>
  <div class="app astrbot-like-shell" data-ui-style="astrbot_like">
    <aside class="sidebar">
      <div class="side-brand">
        <div class="brand-mark" aria-hidden="true">星</div>
        <div>
          <h2>星璇运维MCP</h2>
          <p data-i18n="brand.subtitle">运维审批</p>
        </div>
      </div>
      <nav class="nav" aria-label="Gateway pages">
        <a class="active" href="/approvals">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l7 3v5c0 5-3.2 8.3-7 10-3.8-1.7-7-5-7-10V6l7-3z"></path><path d="M9 12l2 2 4-5"></path></svg>
          <span data-i18n="nav.approvals">审批台</span>
        </a>
        <a href="/config-admin">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5z"></path><path d="M19.4 15a1.8 1.8 0 0 0 .36 1.98l.04.04a2 2 0 1 1-2.83 2.83l-.04-.04A1.8 1.8 0 0 0 15 19.4a1.8 1.8 0 0 0-1 .6V20a2 2 0 1 1-4 0v-.06a1.8 1.8 0 0 0-1-.54 1.8 1.8 0 0 0-1.98.36l-.04.04a2 2 0 1 1-2.83-2.83l.04-.04A1.8 1.8 0 0 0 4.6 15a1.8 1.8 0 0 0-.6-1H4a2 2 0 1 1 0-4h.06a1.8 1.8 0 0 0 .54-1 1.8 1.8 0 0 0-.36-1.98l-.04-.04a2 2 0 1 1 2.83-2.83l.04.04A1.8 1.8 0 0 0 9 4.6a1.8 1.8 0 0 0 1-.6V4a2 2 0 1 1 4 0v.06a1.8 1.8 0 0 0 1 .54 1.8 1.8 0 0 0 1.98-.36l.04-.04a2 2 0 1 1 2.83 2.83l-.04.04A1.8 1.8 0 0 0 19.4 9c.2.36.4.7.6 1H20a2 2 0 1 1 0 4h-.06c-.14.35-.32.68-.54 1z"></path></svg>
          <span data-i18n="nav.config">配置管理</span>
        </a>
        <a href="/gateway-settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16"></path><path d="M4 12h16"></path><path d="M4 18h16"></path><path d="M8 6v4"></path><path d="M16 12v4"></path></svg>
          <span data-i18n="nav.settings">网关设置</span>
        </a>
      </nav>
      <div class="side-footer" data-i18n="footer">人工审批仍通过 MCP 审批工具写入哈希链账本。</div>
    </aside>
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">审</div>
        <div>
          <h1 data-i18n="title">星璇运维MCP 审批台</h1>
          <p id="console-subtitle">approval-console-bundle-v1</p>
        </div>
      </div>
      <div class="top-actions">
        <div class="locale-switch" role="tablist" aria-label="Language">
          <button type="button" data-locale="zh" class="active">中文</button>
          <button type="button" data-locale="en">EN</button>
        </div>
        <span class="pill"><span data-i18n="pill.issuer">签发</span> <strong id="issuer-status">unknown</strong></span>
        <span class="pill"><span data-i18n="pill.identity">身份</span> <strong id="identity-status">unknown</strong></span>
        <span class="pill"><span data-i18n="pill.generated">生成</span> <strong id="generated-at">-</strong></span>
        <span class="pill" id="user-pill" style="background: linear-gradient(135deg, #0f6fbf, #18a0c9); color: white; cursor: pointer;">
          <span id="user-name">-</span>
          <span style="margin-left: 6px; cursor: pointer;" onclick="logout()">×</span>
        </span>
      </div>
    </header>

    <main class="shell">
      <aside class="panel">
        <div class="panel-head">
          <h2 data-i18n="queue.title">审批队列</h2>
          <span class="badge" id="queue-total">0</span>
        </div>
        <div class="panel-body">
          <div class="toolbar">
            <input class="search" id="search" type="search" placeholder="搜索 approval_id / tool / target" data-i18n-placeholder="placeholder.search" />
            <div class="segmented" role="tablist" aria-label="Approval status">
              <button type="button" class="active" data-filter="all" data-i18n="filter.all">全部</button>
              <button type="button" data-filter="pending" data-i18n="filter.open">待审</button>
              <button type="button" data-filter="granted" data-i18n="filter.grant">已批</button>
              <button type="button" data-filter="terminal" data-i18n="filter.stop">终止</button>
            </div>
          </div>
          <div class="approval-list" id="approval-list"></div>
        </div>
      </aside>

      <section class="panel">
        <div class="panel-head">
          <h2 data-i18n="review.title">审核工作区</h2>
          <span class="badge" id="selected-status">-</span>
        </div>
        <div class="panel-body">
          <div class="metrics" id="metrics"></div>
          <div class="detail-grid">
            <div>
              <section class="section">
                <h3 data-i18n="section.operation">操作</h3>
                <dl class="kv" id="operation-kv"></dl>
              </section>
              <section class="section">
                <h3 data-i18n="section.policy">策略</h3>
                <dl class="kv" id="policy-kv"></dl>
              </section>
              <section class="section">
                <h3 data-i18n="section.timeline">时间线</h3>
                <div class="timeline" id="timeline"></div>
              </section>
            </div>
            <div>
              <section class="section">
                <h3 data-i18n="section.lineage">链路</h3>
                <dl class="kv" id="lineage-kv"></dl>
              </section>
              <section class="section">
                <h3 data-i18n="section.payload">载荷</h3>
                <pre id="selected-payload">{}</pre>
              </section>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel rail">
        <div class="panel-head">
          <h2 data-i18n="identity.title">企业身份</h2>
          <span class="badge" id="identity-badge">offline</span>
        </div>
        <div class="panel-body">
          <section class="section">
            <h3 data-i18n="decision.title">审批决定</h3>
            <div class="controls">
              <div class="field">
                <label for="approver" data-i18n="field.approver">审批人</label>
                <input id="approver" autocomplete="off" placeholder="域账号或员工号" data-i18n-placeholder="placeholder.approver" />
              </div>
              <div class="field">
                <label for="enterprise-assertion" data-i18n="field.assertion">企业断言</label>
                <textarea id="enterprise-assertion" spellcheck="false" placeholder="{...签名断言...}" data-i18n-placeholder="placeholder.assertion"></textarea>
              </div>
              <div class="field">
                <label for="gateway-token" data-i18n="field.gateway_token">网关管理员令牌</label>
                <input id="gateway-token" type="password" autocomplete="off" placeholder="托管网关 POST 需要" data-i18n-placeholder="placeholder.gateway_token" />
              </div>
              <div class="button-row">
                <button class="btn primary" id="grant-btn" type="button">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"></path></svg>
                  <span data-i18n="action.grant">批准</span>
                </button>
                <button class="btn danger" id="reject-btn" type="button">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18"></path><path d="M6 6l12 12"></path></svg>
                  <span data-i18n="action.reject">拒绝</span>
                </button>
              </div>
            </div>
          </section>
          <section class="section">
            <h3 data-i18n="section.gateway_result">网关结果</h3>
            <pre id="gateway-result">{}</pre>
          </section>
          <section class="section">
            <h3 data-i18n="section.issue_payload">签发 Token 载荷</h3>
            <pre id="issue-payload">{}</pre>
          </section>
          <section class="section">
            <h3 data-i18n="section.record_payload">记录决定载荷</h3>
            <pre id="record-payload">{}</pre>
          </section>
          <section class="section">
            <h3 data-i18n="section.identity_summary">身份摘要</h3>
            <dl class="kv" id="identity-kv"></dl>
          </section>
        </div>
      </aside>
    </main>
  </div>

  <script>
    const state = JSON.parse(document.getElementById("approval-console-state").textContent);
    let selectedId = state.selected_approval_id;
    let filter = "all";
    let decision = "grant";
    let locale = localStorage.getItem("tmp_mcp_ui_locale") || "zh";

    const $ = (id) => document.getElementById(id);

    function loadSession() {
      const sessionStr = localStorage.getItem("tmp_mcp_session");
      if (!sessionStr) {
        localStorage.setItem("tmp_mcp_redirect", window.location.href);
        window.location.href = "/login";
        return null;
      }
      try {
        return JSON.parse(sessionStr);
      } catch {
        localStorage.removeItem("tmp_mcp_session");
        localStorage.setItem("tmp_mcp_redirect", window.location.href);
        window.location.href = "/login";
        return null;
      }
    }

    function logout() {
      localStorage.removeItem("tmp_mcp_session");
      window.location.href = "/login";
    }

    const session = loadSession();
    if (session && session.approver) {
      document.getElementById("approver").value = session.approver;
      document.getElementById("user-name").textContent = session.username || session.approver;
    }
    const i18n = {
      zh: {
        "brand.subtitle": "运维审批",
        "nav.approvals": "审批台",
        "nav.config": "配置管理",
        "nav.settings": "网关设置",
        "footer": "人工审批仍通过 MCP 审批工具写入哈希链账本。",
        "title": "星璇运维MCP 审批台",
        "pill.issuer": "签发",
        "pill.identity": "身份",
        "pill.generated": "生成",
        "queue.title": "审批队列",
        "filter.all": "全部",
        "filter.open": "待审",
        "filter.grant": "已批",
        "filter.stop": "终止",
        "review.title": "审核工作区",
        "section.operation": "操作",
        "section.policy": "策略",
        "section.timeline": "时间线",
        "section.lineage": "链路",
        "section.payload": "载荷",
        "identity.title": "企业身份",
        "decision.title": "审批决定",
        "field.approver": "审批人",
        "field.assertion": "企业断言",
        "field.gateway_token": "网关管理员令牌",
        "action.grant": "批准",
        "action.reject": "拒绝",
        "section.gateway_result": "网关结果",
        "section.issue_payload": "签发 Token 载荷",
        "section.record_payload": "记录决定载荷",
        "section.identity_summary": "身份摘要",
        "placeholder.search": "搜索 approval_id / tool / target",
        "placeholder.approver": "域账号或员工号",
        "placeholder.assertion": "{...签名断言...}",
        "placeholder.gateway_token": "托管网关 POST 需要",
        "status.enabled": "启用",
        "status.disabled": "禁用",
        "status.required": "必需",
        "status.optional": "可选",
        "status.online": "在线",
        "status.offline": "离线",
        "metric.open": "待审",
        "metric.granted": "已批准",
        "metric.high_risk": "高风险",
        "metric.verified_id": "已验证身份",
        "empty.approvals": "暂无审批",
        "empty.timeline": "暂无时间线",
        "fallback.requester": "请求人：-",
        "error.required": "approval_id 和审批人必填",
        "error.fetch": "当前页面无法调用托管网关 fetch API",
        "error.gateway": "网关请求失败"
      },
      en: {
        "brand.subtitle": "operations approval",
        "nav.approvals": "Approvals",
        "nav.config": "Config Admin",
        "nav.settings": "Gateway Settings",
        "footer": "Manual approvals still write through MCP approval tools and the hash-linked ledger.",
        "title": "Xingxuan MCP Approval Console",
        "pill.issuer": "issuer",
        "pill.identity": "identity",
        "pill.generated": "generated",
        "queue.title": "Approval Queue",
        "filter.all": "All",
        "filter.open": "Open",
        "filter.grant": "Grant",
        "filter.stop": "Stop",
        "review.title": "Review Workspace",
        "section.operation": "Operation",
        "section.policy": "Policy",
        "section.timeline": "Timeline",
        "section.lineage": "Lineage",
        "section.payload": "Payload",
        "identity.title": "Enterprise Identity",
        "decision.title": "Decision",
        "field.approver": "approver",
        "field.assertion": "enterprise_assertion",
        "field.gateway_token": "gateway_admin_token",
        "action.grant": "Grant",
        "action.reject": "Reject",
        "section.gateway_result": "Gateway Result",
        "section.issue_payload": "Issue Token Payload",
        "section.record_payload": "Record Decision Payload",
        "section.identity_summary": "Identity Summary",
        "placeholder.search": "approval_id / tool / target",
        "placeholder.approver": "domain\\\\user or employee id",
        "placeholder.assertion": "{...signed assertion...}",
        "placeholder.gateway_token": "required for hosted gateway POST",
        "status.enabled": "enabled",
        "status.disabled": "disabled",
        "status.required": "required",
        "status.optional": "optional",
        "status.online": "online",
        "status.offline": "offline",
        "metric.open": "Open",
        "metric.granted": "Granted",
        "metric.high_risk": "High Risk",
        "metric.verified_id": "Verified ID",
        "empty.approvals": "No approvals",
        "empty.timeline": "No timeline",
        "fallback.requester": "requester: -",
        "error.required": "approval_id and approver are required",
        "error.fetch": "hosted gateway fetch API is unavailable in this surface",
        "error.gateway": "gateway request failed"
      }
    };
    const tr = (key) => (i18n[locale] && i18n[locale][key]) || (i18n.en && i18n.en[key]) || key;
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\\"": "&quot;", "'": "&#39;"
    }[ch]));
    const pretty = (value) => JSON.stringify(value ?? {}, null, 2);
    const statusClass = (value) => String(value || "").replace(/[^a-z0-9_-]/gi, "_");

    function bindLocale() {
      document.querySelectorAll("[data-locale]").forEach((button) => {
        button.addEventListener("click", () => {
          locale = button.dataset.locale || "zh";
          localStorage.setItem("tmp_mcp_ui_locale", locale);
          renderAll();
        });
      });
    }

    function applyLocale() {
      document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
      document.querySelectorAll("[data-i18n]").forEach((node) => {
        node.textContent = tr(node.dataset.i18n);
      });
      document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
        node.setAttribute("placeholder", tr(node.dataset.i18nPlaceholder));
      });
      document.querySelectorAll("[data-locale]").forEach((button) => {
        button.classList.toggle("active", button.dataset.locale === locale);
      });
    }

    function selectedApproval() {
      return state.approvals.find((item) => item.approval_id === selectedId) || state.approvals[0] || {};
    }

    function filteredApprovals() {
      const query = $("search").value.trim().toLowerCase();
      return state.approvals.filter((item) => {
        const status = String(item.status || "");
        const text = [item.approval_id, item.tool_name, item.operation, item.target, item.requester].join(" ").toLowerCase();
        const matchesFilter =
          filter === "all" ||
          (filter === "pending" && ["requested", "partially_granted"].includes(status)) ||
          (filter === "terminal" && ["rejected", "revoked", "expired"].includes(status)) ||
          status === filter;
        return matchesFilter && (!query || text.includes(query));
      });
    }

    function renderChrome() {
      $("console-subtitle").textContent = state.schema_version;
      $("generated-at").textContent = state.generated_at || "-";
      const mode = state.identity_mode || {};
      $("issuer-status").textContent = mode.enterprise_token_issuer_enabled ? tr("status.enabled") : tr("status.disabled");
      $("identity-status").textContent = mode.approval_identity_required ? tr("status.required") : tr("status.optional");
      $("identity-badge").textContent = mode.enterprise_token_issuer_enabled ? tr("status.online") : tr("status.offline");
      $("identity-badge").className = "badge " + (mode.enterprise_token_issuer_enabled ? "granted" : "rejected");
      $("queue-total").textContent = String(state.approvals.length || 0);
    }

    function renderMetrics() {
      const metrics = state.metrics || {};
      const items = [
        [tr("metric.open"), metrics.pending],
        [tr("metric.granted"), metrics.granted],
        [tr("metric.high_risk"), metrics.high_risk],
        [tr("metric.verified_id"), metrics.verified_identity_count],
      ];
      $("metrics").innerHTML = items.map(([label, value]) =>
        `<div class="metric"><span>${esc(label)}</span><strong>${esc(value ?? 0)}</strong></div>`
      ).join("");
    }

    function renderList() {
      const items = filteredApprovals();
      $("approval-list").innerHTML = items.length ? items.map((item) => `
        <button type="button" class="approval-item ${item.approval_id === selectedId ? "active" : ""}" data-id="${esc(item.approval_id)}">
          <div class="row">
            <span class="id">${esc(item.approval_id)}</span>
            <span class="badge ${statusClass(item.status)}">${esc(item.status)}</span>
          </div>
          <p class="title">${esc(item.tool_name)} / ${esc(item.operation)}</p>
          <p class="subtle">${esc(item.target)} · ${esc(item.requester || tr("fallback.requester"))}</p>
          <div class="row">
            <span class="badge ${statusClass(item.risk_level)}">${esc(item.risk_level)}</span>
            <span class="subtle">${esc(item.updated_at || item.created_at || "-")}</span>
          </div>
        </button>
      `).join("") : `<div class="empty">${tr("empty.approvals")}</div>`;
      document.querySelectorAll(".approval-item").forEach((button) => {
        button.addEventListener("click", () => {
          selectedId = button.dataset.id;
          renderAll();
        });
      });
    }

    function renderKv(id, pairs) {
      $(id).innerHTML = pairs.map(([key, value]) =>
        `<dt>${esc(key)}</dt><dd>${esc(formatValue(value))}</dd>`
      ).join("");
    }

    function formatValue(value) {
      if (Array.isArray(value)) return value.join(", ") || "-";
      if (value && typeof value === "object") return JSON.stringify(value);
      return value ?? "-";
    }

    function renderDetail() {
      const approval = selectedApproval();
      const packet = state.review_packet || {};
      const operation = packet.operation || {};
      const policy = packet.policy || {};
      const lineage = packet.lineage || {};
      const identity = packet.identity || {};
      $("selected-status").textContent = approval.status || packet.status || "-";
      $("selected-status").className = "badge " + statusClass(approval.status || packet.status);

      renderKv("operation-kv", [
        ["approval_id", approval.approval_id || packet.approval_id],
        ["tool_name", operation.tool_name || approval.tool_name],
        ["operation", operation.operation || approval.operation],
        ["target", operation.target || approval.target],
        ["scope_hash", operation.scope_hash || approval.scope_hash],
        ["trace_id", packet.trace_id || approval.trace_id],
      ]);
      renderKv("policy-kv", [
        ["required", policy.required_approvals ?? approval.required_approvals],
        ["granted", policy.granted_approvals ?? approval.granted_approvals],
        ["remaining", policy.remaining_approvals],
        ["distinct", policy.require_distinct_approvers],
        ["self_approval", policy.allow_self_approval],
        ["rules", policy.policy_rule_ids || approval.policy_rule_ids],
        ["allowed_ids", policy.allowed_approver_ids],
      ]);
      renderKv("lineage-kv", [
        ["ledger_history", lineage.ledger_history_count],
        ["audit_events", (packet.audit || {}).event_count],
        ["latest_identity", identity.latest_identity ? identity.latest_identity.provider : "-"],
        ["event_hash", lineage.event_hash || approval.event_hash],
        ["prev_hash", lineage.prev_hash || approval.prev_hash],
        ["expires_at", lineage.expires_at || approval.expires_at],
      ]);
      $("selected-payload").textContent = pretty({ approval, review_packet: packet });
      renderTimeline(packet.timeline || []);
      renderIdentity();
      renderPayloads();
    }

    function renderTimeline(items) {
      $("timeline").innerHTML = items.length ? items.slice(0, 40).map((item) => `
        <div class="timeline-item ${esc(item.source)}">
          <span class="dot" aria-hidden="true"></span>
          <div class="timeline-copy">
            <div class="row">
              <strong class="title">${esc(item.event_type)}</strong>
              <span class="badge">${esc(item.source)}</span>
            </div>
            <p class="subtle">${esc(item.timestamp || "-")}</p>
            <p class="subtle">${esc(item.summary || item.decision || "-")}</p>
          </div>
        </div>
      `).join("") : `<div class="empty">${tr("empty.timeline")}</div>`;
    }

    function renderIdentity() {
      const mode = state.identity_mode || {};
      const packetIdentity = (state.review_packet || {}).identity || {};
      renderKv("identity-kv", [
        ["approval_identity_required", mode.approval_identity_required],
        ["scope_binding_required", mode.scope_binding_required],
        ["enterprise_issuer_enabled", mode.enterprise_token_issuer_enabled],
        ["enterprise_role", mode.enterprise_approver_role || "ops_approver"],
        ["allowed_issuers", mode.enterprise_allowed_issuers || []],
        ["verified_identity_count", packetIdentity.verified_identity_count || 0],
      ]);
    }

    function renderPayloads() {
      const approval = selectedApproval();
      const approver = $("approver").value.trim();
      const assertionRaw = $("enterprise-assertion").value.trim();
      const assertion = parseAssertion(assertionRaw);
      const issuePayload = {
        endpoint: "/api/approvals/issue-token",
        tool: state.mcp_contract.issue_token_tool,
        arguments: {
          approval_id: approval.approval_id || selectedId,
          decision,
          approver,
          enterprise_assertion: assertion,
        },
      };
      const recordPayload = {
        endpoint: "/api/approvals/decision",
        tool: state.mcp_contract.record_tool,
        arguments: {
          approval_id: approval.approval_id || selectedId,
          decision,
          approver,
          approval_token: "<issued by issue_enterprise_approval_token_tool>",
        },
      };
      $("issue-payload").textContent = pretty(issuePayload);
      $("record-payload").textContent = pretty(recordPayload);
    }

    async function submitDecision(nextDecision) {
      decision = nextDecision;
      renderPayloads();
      const approval = selectedApproval();
      const approvalId = approval.approval_id || selectedId;
      const approver = $("approver").value.trim();
      const rawAssertion = $("enterprise-assertion").value.trim();
      const adminToken = $("gateway-token").value.trim();
      if (!approvalId || !approver) {
        showGatewayResult({ ok: false, summary: tr("error.required") });
        return;
      }
      if (!window.fetch || !location.protocol.startsWith("http")) {
        showGatewayResult({ ok: false, summary: tr("error.fetch") });
        return;
      }
      try {
        let approvalToken = null;
        if (rawAssertion) {
          const issued = await callGateway("/api/approvals/issue-token", {
            approval_id: approvalId,
            decision,
            approver,
            enterprise_assertion: parseAssertion(rawAssertion),
          }, adminToken);
          if (!issued.ok) {
            showGatewayResult(issued);
            return;
          }
          approvalToken = issued.data && issued.data.approval_token;
        }
        const recorded = await callGateway("/api/approvals/decision", {
          approval_id: approvalId,
          decision,
          approver,
          approval_token: approvalToken,
          comment: "submitted from hosted B/S approval console",
        }, adminToken);
        showGatewayResult(recorded);
        if (recorded.ok) {
          window.setTimeout(() => window.location.reload(), 700);
        }
      } catch (error) {
        showGatewayResult({ ok: false, summary: tr("error.gateway"), data: { error: String(error) } });
      }
    }

    async function callGateway(path, payload, adminToken) {
      const headers = { "Content-Type": "application/json" };
      if (adminToken) headers["X-TMP-MCP-Admin-Token"] = adminToken;
      const response = await fetch(path, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      const text = await response.text();
      let parsed;
      try { parsed = JSON.parse(text); }
      catch { parsed = { ok: false, summary: text || response.statusText }; }
      parsed.http_status = response.status;
      if (!response.ok && parsed.ok !== false) parsed.ok = false;
      return parsed;
    }

    function showGatewayResult(payload) {
      $("gateway-result").textContent = pretty(payload);
    }

    function parseAssertion(raw) {
      if (!raw) return null;
      try { return JSON.parse(raw); }
      catch { return raw; }
    }

    function renderAll() {
      applyLocale();
      renderChrome();
      renderMetrics();
      renderList();
      renderDetail();
    }

    document.querySelectorAll(".segmented button").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        filter = button.dataset.filter;
        renderList();
      });
    });
    $("search").addEventListener("input", renderList);
    $("approver").addEventListener("input", renderPayloads);
    $("enterprise-assertion").addEventListener("input", renderPayloads);
    $("grant-btn").addEventListener("click", () => { submitDecision("grant"); });
    $("reject-btn").addEventListener("click", () => { submitDecision("reject"); });

    bindLocale();
    renderAll();
  </script>
</body>
</html>
"""
