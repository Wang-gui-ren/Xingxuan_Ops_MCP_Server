from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


CONFIG_ADMIN_CONSOLE_SCHEMA_VERSION = "config-admin-console-bundle-v1"


def build_config_admin_console_bundle(
    *,
    config_state: dict[str, Any],
    audit_events: list[dict[str, Any]] | None = None,
    validation_result: dict[str, Any] | None = None,
    include_html: bool = True,
) -> dict[str, Any]:
    state = {
        "schema_version": CONFIG_ADMIN_CONSOLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": dict(config_state),
        "audit_events": list(audit_events or []),
        "validation_result": dict(validation_result or {}),
        "metrics": _metrics(config_state, audit_events or []),
        "mcp_contract": {
            "read_tool": "get_approval_identity_config_tool",
            "validate_tool": "validate_approval_identity_config_tool",
            "update_tool": "update_approval_identity_config_tool",
            "rotate_secret_tool": "rotate_approval_identity_secret_tool",
            "bundle_tool": "get_config_admin_console_bundle_tool",
            "admin_assertion_field": "admin_identity_assertion",
        },
    }
    bundle = {
        "schema_version": CONFIG_ADMIN_CONSOLE_SCHEMA_VERSION,
        "generated_at": state["generated_at"],
        "design_system": _design_system(),
        "state": state,
    }
    if include_html:
        bundle["html"] = _render_html(state)
    return bundle


def _metrics(config_state: dict[str, Any], audit_events: list[dict[str, Any]]) -> dict[str, Any]:
    effective = config_state.get("effective_config") if isinstance(config_state.get("effective_config"), dict) else {}
    secret_status = config_state.get("secret_status") if isinstance(config_state.get("secret_status"), dict) else {}
    configured_secrets = 0
    usable_secrets = 0
    for item in secret_status.values():
        if isinstance(item, dict):
            configured_secrets += 1 if item.get("configured") else 0
            usable_secrets += 1 if item.get("usable_for_hmac") else 0
    return {
        "identity_enforced": bool(effective.get("require_approval_identity")),
        "scope_binding_required": bool(effective.get("require_approval_identity_scope")),
        "enterprise_issuer_enabled": bool(effective.get("enterprise_token_issuer_enabled")),
        "configured_secret_count": configured_secrets,
        "usable_secret_count": usable_secrets,
        "audit_event_count": len(audit_events),
        "warning_count": len(config_state.get("warnings") or []),
    }


def _design_system() -> dict[str, Any]:
    return {
        "name": "tmp-mcp-semi-design-config-admin-console",
        "palette": {
            "background": "#f5f6fa",
            "surface": "#ffffff",
            "ink": "#1c1f23",
            "muted": "#646a73",
            "line": "#dee0e3",
            "primary": "#0064fa",
            "accent": "#3370ff",
            "success": "#00a870",
            "warning": "#f5a623",
            "danger": "#f93920",
        },
        "radius_px": 6,
        "font_stack": "Inter, Segoe UI, system-ui, sans-serif",
        "mono_stack": "Fira Code, Consolas, ui-monospace, monospace",
        "component_basis": "Card, Form, Input, TextArea, Button, Tag, Timeline",
    }


def _render_html(state: dict[str, Any]) -> str:
    return _HTML_TEMPLATE.replace("__STATE_JSON__", _safe_script_json(state))


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
  <title>星璇运维MCP 配置管理</title>
  <meta name="design-system" content="Semi Design" />
  <link rel="stylesheet" href="https://unpkg.com/@douyinfe/semi-ui@2.27.0/dist/css/semi.css" />
  <style>
    :root {
      color-scheme: light;
      --bg: var(--semi-color-fill-0, #f3f8fc);
      --surface: var(--semi-color-bg-2, #ffffff);
      --sidebar: rgba(255, 255, 255, 0.94);
      --ink: var(--semi-color-text-0, #0f172a);
      --muted: var(--semi-color-text-2, #5b6b82);
      --line: var(--semi-color-border, #d8e4ee);
      --soft-line: var(--semi-color-border, #eaf1f6);
      --primary: var(--semi-color-primary, #0f6fbf);
      --primary-hover: var(--semi-color-primary-hover, #0b5f9d);
      --accent: var(--semi-color-primary, #18a0c9);
      --light-primary: var(--semi-color-primary-light-default, #e6f5fb);
      --light-secondary: var(--semi-color-fill-0, #f7f8fa);
      --success: var(--semi-color-success, #00a870);
      --warning: var(--semi-color-warning, #f5a623);
      --danger: var(--semi-color-danger, #f93920);
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
      font-size: 14px;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      grid-template-rows: auto 1fr;
    }
    .semi-design-shell {
      background:
        linear-gradient(180deg, rgba(232, 243, 255, 0.65) 0, rgba(245, 246, 250, 0) 270px),
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
      gap: 16px;
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      padding: 16px 12px;
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
      min-height: 38px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 10px;
      border-radius: var(--radius);
      color: var(--semi-color-text-1, #373c43);
      text-decoration: none;
      font-size: 13px;
      transition: background 140ms ease, color 140ms ease;
    }
    .nav a:hover { background: var(--light-primary); color: var(--primary); }
    .nav a.active {
      background: var(--light-primary);
      color: var(--primary);
      font-weight: 700;
      box-shadow: inset 3px 0 0 var(--primary);
    }
    .nav svg { width: 17px; height: 17px; flex: 0 0 auto; }
    .side-footer {
      margin-top: auto;
      padding: 10px;
      border: 1px solid var(--soft-line);
      border-radius: var(--radius);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      background: var(--semi-color-fill-0, #f7f8fa);
    }
    .topbar {
      grid-column: 2;
      grid-row: 1;
      display: grid;
      grid-template-columns: minmax(240px, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 14px 20px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      position: sticky;
      top: 0;
      z-index: 2;
      backdrop-filter: blur(12px);
    }
    .brand {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .mark {
      width: 34px;
      height: 34px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, var(--primary), #00a3ff);
      color: white;
      font-weight: 800;
      flex: 0 0 auto;
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 17px; line-height: 1.15; letter-spacing: 0; }
    .sub { margin-top: 3px; font-size: 12px; color: var(--muted); }
    .chips {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }
    .top-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      align-items: center;
      gap: 8px;
    }
    .locale-switch {
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(42px, 1fr));
      padding: 2px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-fill-0, #f7f8fa);
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
      background: var(--semi-color-bg-2, #fff);
      color: var(--primary);
      box-shadow: 0 2px 6px rgba(31, 35, 41, 0.1);
    }
    .chip {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid transparent;
      border-radius: var(--radius);
      background: var(--semi-color-fill-0, #f7f8fa);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .chip strong { margin-left: 6px; color: var(--ink); }
    .layout {
      grid-column: 2;
      grid-row: 2;
      display: grid;
      grid-template-columns: minmax(0, 960px);
      justify-content: center;
      align-content: start;
      gap: 16px;
      padding: 16px;
      min-height: 0;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-width: 0;
    }
    .panel {
      min-width: 0;
      overflow: hidden;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 11px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--semi-color-bg-2, #fff);
    }
    .panel-head h2 { font-size: 13px; letter-spacing: 0; }
    .panel-body { padding: 14px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      min-height: 74px;
      background: var(--semi-color-fill-0, #f7f8fa);
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 8px;
      font-size: 22px;
      line-height: 1;
    }
    .rows {
      display: grid;
      gap: 8px;
    }
    .row {
      display: grid;
      grid-template-columns: 190px minmax(0, 1fr);
      gap: 10px;
      padding: 9px 0;
      border-bottom: 1px solid var(--soft-line);
      align-items: start;
    }
    .row:last-child { border-bottom: 0; }
    .label {
      color: var(--muted);
      font-size: 12px;
    }
    .value {
      min-width: 0;
      overflow-wrap: anywhere;
      font-size: 13px;
      font-family: "Fira Code", Consolas, ui-monospace, monospace;
    }
    .status {
      display: inline-flex;
      min-height: 24px;
      align-items: center;
      padding: 3px 7px;
      border-radius: var(--radius);
      font-size: 12px;
      border: 1px solid transparent;
      background: var(--semi-color-fill-0, #f7f8fa);
    }
    .on {
      color: var(--semi-color-success, #00a870);
      background: var(--semi-color-success-light-default, #e9f8f3);
    }
    .off { color: var(--muted); }
    .warn {
      color: var(--semi-color-warning, #f5a623);
      background: var(--semi-color-warning-light-default, #fff7e6);
    }
    pre {
      margin: 0;
      max-height: 440px;
      overflow: auto;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-fill-0, #f7f8fa);
      color: var(--ink);
      font-size: 12px;
      line-height: 1.45;
      font-family: "Fira Code", Consolas, ui-monospace, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .timeline {
      display: grid;
      gap: 9px;
      max-height: 310px;
      overflow: auto;
    }
    .event {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 9px;
      background: var(--semi-color-bg-2, #fff);
      transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
    }
    .event:hover {
      border-color: rgba(0, 100, 250, 0.35);
      background: var(--semi-color-primary-light-default, #f0f7ff);
      box-shadow: 0 2px 8px rgba(31, 35, 41, 0.06);
    }
    .event strong {
      display: block;
      font-size: 12px;
      margin-bottom: 4px;
    }
    .event span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .form {
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
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-bg-0, #fff);
      color: var(--ink);
      padding: 7px 11px;
      font: 12px/1.4 "Fira Code", Consolas, ui-monospace, monospace;
      resize: vertical;
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }
    .field input:hover, .field textarea:hover { border-color: var(--primary); }
    .field input:focus, .field textarea:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(0, 100, 250, 0.12);
    }
    .field textarea { min-height: 92px; }
    .actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    button {
      min-height: 36px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--semi-color-bg-2, #fff);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-weight: 600;
      transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }
    button:hover {
      border-color: var(--primary);
      color: var(--primary);
    }
    button.primary {
      border-color: var(--primary);
      background: var(--primary);
      color: #fff;
    }
    button.primary:hover {
      border-color: var(--primary-hover);
      background: var(--primary-hover);
      color: #fff;
    }
    button:focus-visible, input:focus-visible, textarea:focus-visible {
      outline: 3px solid rgba(0, 100, 250, 0.22);
      outline-offset: 2px;
    }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
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
      .topbar {
        grid-column: 1;
        grid-row: 2;
      }
      .layout {
        grid-column: 1;
        grid-row: 3;
      }
      .layout { grid-template-columns: 1fr; }
      .topbar { grid-template-columns: 1fr; }
      .chips { justify-content: flex-start; }
    }
    @media (max-width: 620px) {
      .grid, .row { grid-template-columns: 1fr; }
      .layout { padding: 10px; }
      .nav { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <script id="config-admin-console-state" type="application/json">__STATE_JSON__</script>
  <main class="app astrbot-like-shell semi-design-shell" data-ui-style="semi_design" data-design-system="semi-design">
    <aside class="sidebar semi-navigation" data-semi-component="Navigation">
      <div class="side-brand">
        <div class="mark">星</div>
        <div>
          <h2>星璇运维MCP</h2>
          <p data-i18n="config.brand.subtitle">身份可信配置</p>
        </div>
      </div>
      <nav class="nav" aria-label="Gateway pages">
        <a class="semi-navigation-item" href="/approvals">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l7 3v5c0 5-3.2 8.3-7 10-3.8-1.7-7-5-7-10V6l7-3z"></path><path d="M9 12l2 2 4-5"></path></svg>
          <span data-i18n="nav.approvals">审批台</span>
        </a>
        <a class="active semi-navigation-item semi-navigation-item-selected" href="/config-admin">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5z"></path><path d="M19.4 15a1.8 1.8 0 0 0 .36 1.98l.04.04a2 2 0 1 1-2.83 2.83l-.04-.04A1.8 1.8 0 0 0 15 19.4a1.8 1.8 0 0 0-1 .6V20a2 2 0 1 1-4 0v-.06a1.8 1.8 0 0 0-1-.54 1.8 1.8 0 0 0-1.98.36l-.04.04a2 2 0 1 1-2.83-2.83l.04-.04A1.8 1.8 0 0 0 4.6 15a1.8 1.8 0 0 0-.6-1H4a2 2 0 1 1 0-4h.06a1.8 1.8 0 0 0 .54-1 1.8 1.8 0 0 0-.36-1.98l-.04-.04a2 2 0 1 1 2.83-2.83l.04.04A1.8 1.8 0 0 0 9 4.6a1.8 1.8 0 0 0 1-.6V4a2 2 0 1 1 4 0v.06a1.8 1.8 0 0 0 1 .54 1.8 1.8 0 0 0 1.98-.36l.04-.04a2 2 0 1 1 2.83 2.83l-.04.04A1.8 1.8 0 0 0 19.4 9c.2.36.4.7.6 1H20a2 2 0 1 1 0 4h-.06c-.14.35-.32.68-.54 1z"></path></svg>
          <span data-i18n="nav.config">配置管理</span>
        </a>
        <a class="semi-navigation-item" href="/gateway-settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16"></path><path d="M4 12h16"></path><path d="M4 18h16"></path><path d="M8 6v4"></path><path d="M16 12v4"></path></svg>
          <span data-i18n="nav.settings">网关设置</span>
        </a>
      </nav>
      <div class="side-footer" data-i18n="config.footer">配置变更仍需要可信管理员身份断言。</div>
    </aside>
    <header class="topbar">
      <div class="brand">
        <div class="mark">配</div>
        <div>
          <h1 data-i18n="config.title">星璇运维MCP 配置管理</h1>
          <p class="sub" id="generatedAt"></p>
        </div>
      </div>
      <div class="top-actions">
        <div class="locale-switch" role="tablist" aria-label="Language">
          <button type="button" data-locale="zh" class="active">中文</button>
          <button type="button" data-locale="en">EN</button>
        </div>
        <div class="chips" id="chips"></div>
        <span class="chip semi-tag" id="user-pill" style="background: linear-gradient(135deg, #0064fa, #3370ff); color: white; cursor: pointer; margin-left: 8px;">
          <span id="user-name">-</span>
          <span style="margin-left: 6px; cursor: pointer;" onclick="logout()">×</span>
        </span>
      </div>
    </header>
    <section class="layout">
      <div class="stack">
        <article class="panel semi-card" data-semi-component="Card">
          <div class="panel-head"><h2 data-i18n="config.identity_mode">身份模式</h2><span class="status semi-tag" id="modeStatus"></span></div>
          <div class="panel-body">
            <div class="grid" id="metrics"></div>
          </div>
        </article>
        <article class="panel semi-card" data-semi-component="Card">
          <div class="panel-head"><h2 data-i18n="config.effective_config">生效配置</h2></div>
          <div class="panel-body"><div class="rows" id="configRows"></div></div>
        </article>
        <article class="panel semi-card" data-semi-component="Card">
          <div class="panel-head"><h2 data-i18n="config.secret_status">密钥状态</h2></div>
          <div class="panel-body"><div class="rows" id="secretRows"></div></div>
        </article>
      </div>
      <div class="stack">
        <article class="panel semi-card" data-semi-component="Card">
          <div class="panel-head"><h2 data-i18n="config.validation">校验结果</h2><span class="status semi-tag" id="validationStatus"></span></div>
          <div class="panel-body"><pre id="validationJson"></pre></div>
        </article>
        <article class="panel semi-card" data-semi-component="Form">
          <div class="panel-head"><h2 data-i18n="config.actions">网关操作</h2><span class="status semi-tag" id="actionStatus">idle</span></div>
          <div class="panel-body">
            <div class="form">
              <div class="field">
                <label for="gatewayToken">gateway_admin_token</label>
                <input class="semi-input" id="gatewayToken" type="password" autocomplete="off" placeholder="required for hosted gateway POST" />
              </div>
              <div class="field">
                <label for="adminApprover">admin_approver</label>
                <input class="semi-input" id="adminApprover" autocomplete="off" placeholder="security-admin" />
              </div>
              <div class="field">
                <label for="adminAssertion">admin_identity_assertion</label>
                <textarea class="semi-input-textarea" id="adminAssertion" spellcheck="false" placeholder="{...signed admin assertion...}"></textarea>
              </div>
              <div class="field">
                <label for="configPatch">config_patch</label>
                <textarea class="semi-input-textarea" id="configPatch" spellcheck="false">{"identity":{"require_approval_identity":true}}</textarea>
              </div>
              <div class="actions">
                <button class="semi-button" type="button" id="validatePatch" data-i18n="action.validate">校验</button>
                <button class="primary semi-button semi-button-primary" type="button" id="updatePatch" data-i18n="action.update">更新</button>
              </div>
              <pre id="actionResult">{}</pre>
            </div>
          </div>
        </article>
        <article class="panel semi-card" data-semi-component="Timeline">
          <div class="panel-head"><h2 data-i18n="config.audit_timeline">审计时间线</h2><span class="status semi-tag" id="eventCount"></span></div>
          <div class="panel-body"><div class="timeline" id="timeline"></div></div>
        </article>
        <article class="panel semi-card" data-semi-component="Card">
          <div class="panel-head"><h2 data-i18n="config.mcp_contract">MCP 契约</h2></div>
          <div class="panel-body"><pre id="contractJson"></pre></div>
        </article>
      </div>
    </section>
  </main>
  <script>
    const state = JSON.parse(document.getElementById("config-admin-console-state").textContent);
    const config = state.config || {};
    const effective = config.effective_config || {};
    const secretStatus = config.secret_status || {};
    const metrics = state.metrics || {};
    let locale = localStorage.getItem("tmp_mcp_ui_locale") || "zh";

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
    if (session && session.username) {
      document.getElementById("user-name").textContent = session.username;
      document.getElementById("adminApprover").value = session.username;
    }
    const i18n = {
      zh: {
        "config.brand.subtitle": "身份可信配置",
        "nav.approvals": "审批台",
        "nav.config": "配置管理",
        "nav.settings": "网关设置",
        "config.footer": "配置变更仍需要可信管理员身份断言。",
        "config.title": "星璇运维MCP 配置管理",
        "config.generated": "生成时间",
        "config.identity_mode": "身份模式",
        "config.effective_config": "生效配置",
        "config.secret_status": "密钥状态",
        "config.validation": "校验结果",
        "config.actions": "网关操作",
        "config.audit_timeline": "审计时间线",
        "config.mcp_contract": "MCP 契约",
        "action.validate": "校验",
        "action.update": "更新",
        "status.enforced": "强制",
        "status.compatible": "兼容",
        "status.on": "开",
        "status.off": "关",
        "status.none": "无",
        "status.pass": "通过",
        "status.attention": "注意",
        "status.ok": "成功",
        "metric.identity": "身份",
        "metric.scope": "范围绑定",
        "metric.enterprise": "企业签发",
        "metric.usable_secrets": "可用密钥",
        "unit.events": "条事件",
        "empty.audit": "暂无审计事件"
      },
      en: {
        "config.brand.subtitle": "identity configuration",
        "nav.approvals": "Approvals",
        "nav.config": "Config Admin",
        "nav.settings": "Gateway Settings",
        "config.footer": "Config changes still require trusted admin identity assertions.",
        "config.title": "Xingxuan MCP Config Admin",
        "config.generated": "Generated",
        "config.identity_mode": "Identity Mode",
        "config.effective_config": "Effective Config",
        "config.secret_status": "Secret Status",
        "config.validation": "Validation",
        "config.actions": "Gateway Actions",
        "config.audit_timeline": "Audit Timeline",
        "config.mcp_contract": "MCP Contract",
        "action.validate": "Validate",
        "action.update": "Update",
        "status.enforced": "enforced",
        "status.compatible": "compatible",
        "status.on": "on",
        "status.off": "off",
        "status.none": "none",
        "status.pass": "pass",
        "status.attention": "attention",
        "status.ok": "ok",
        "metric.identity": "identity",
        "metric.scope": "scope",
        "metric.enterprise": "enterprise",
        "metric.usable_secrets": "usable secrets",
        "unit.events": "event(s)",
        "empty.audit": "No audit events"
      }
    };
    const tr = (key) => (i18n[locale] && i18n[locale][key]) || (i18n.en && i18n.en[key]) || key;
    const text = (value) => Array.isArray(value) ? value.join(", ") : String(value ?? "");
    const boolStatus = (value) => `<span class="status semi-tag ${value ? "on" : "off"}">${value ? tr("status.on") : tr("status.off")}</span>`;
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
      document.querySelectorAll("[data-locale]").forEach((button) => {
        button.classList.toggle("active", button.dataset.locale === locale);
      });
      document.getElementById("generatedAt").textContent = `${tr("config.generated")} ${state.generated_at || ""}`;
    }
    function renderAll() {
      applyLocale();
      document.getElementById("modeStatus").className = `status semi-tag ${metrics.identity_enforced ? "on" : "off"}`;
      document.getElementById("modeStatus").textContent = metrics.identity_enforced ? tr("status.enforced") : tr("status.compatible");
    document.getElementById("chips").innerHTML = [
      ["schema", state.schema_version],
      ["warnings", metrics.warning_count],
      ["audit", metrics.audit_event_count]
    ].map(([k, v]) => `<span class="chip semi-tag">${k}<strong>${v}</strong></span>`).join("");
    document.getElementById("metrics").innerHTML = [
      [tr("metric.identity"), metrics.identity_enforced ? tr("status.on") : tr("status.off")],
      [tr("metric.scope"), metrics.scope_binding_required ? tr("status.on") : tr("status.off")],
      [tr("metric.enterprise"), metrics.enterprise_issuer_enabled ? tr("status.on") : tr("status.off")],
      [tr("metric.usable_secrets"), metrics.usable_secret_count]
    ].map(([k, v]) => `<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join("");
    document.getElementById("configRows").innerHTML = Object.entries(effective).map(([key, value]) => {
      const rendered = typeof value === "boolean" ? boolStatus(value) : text(value);
      return `<div class="row"><div class="label">${key}</div><div class="value">${rendered}</div></div>`;
    }).join("");
    document.getElementById("secretRows").innerHTML = Object.entries(secretStatus).map(([key, value]) => {
      const safe = {
        configured: Boolean(value && value.configured),
        usable_for_hmac: Boolean(value && value.usable_for_hmac),
        source: value && value.source,
        secret_ref: value && value.secret_ref,
        key_id: value && value.key_id,
        fingerprint: value && value.fingerprint
      };
      return `<div class="row"><div class="label">${key}</div><div class="value"><pre>${JSON.stringify(safe, null, 2)}</pre></div></div>`;
    }).join("");
    const validation = state.validation_result || {};
    const validationOk = validation.ok === true;
    const validationEmpty = Object.keys(validation).length === 0;
    document.getElementById("validationStatus").className = `status semi-tag ${validationEmpty ? "off" : validationOk ? "on" : "warn"}`;
    document.getElementById("validationStatus").textContent = validationEmpty ? tr("status.none") : validationOk ? tr("status.pass") : tr("status.attention");
    document.getElementById("validationJson").textContent = JSON.stringify(validation, null, 2);
    document.getElementById("eventCount").textContent = `${(state.audit_events || []).length} ${tr("unit.events")}`;
    document.getElementById("timeline").innerHTML = (state.audit_events || []).map((event) => (
      `<div class="event"><strong>${event.event_type || "event"}</strong><span>${event.timestamp || ""}</span><span>${event.decision || ""}</span></div>`
    )).join("") || `<div class="event"><strong>${tr("empty.audit")}</strong><span></span></div>`;
    document.getElementById("contractJson").textContent = JSON.stringify(state.mcp_contract || {}, null, 2);
    }
    bindLocale();
    renderAll();

    const actionStatus = document.getElementById("actionStatus");
    const actionResult = document.getElementById("actionResult");
    const parseJsonField = (id) => {
      const raw = document.getElementById(id).value.trim();
      if (!raw) return null;
      return JSON.parse(raw);
    };
    const setActionResult = (payload) => {
      actionStatus.className = `status semi-tag ${payload && payload.ok ? "on" : "warn"}`;
      actionStatus.textContent = payload && payload.ok ? tr("status.ok") : tr("status.attention");
      actionResult.textContent = JSON.stringify(payload || {}, null, 2);
    };
    async function callGateway(path, payload) {
      const token = document.getElementById("gatewayToken").value.trim();
      const headers = { "Content-Type": "application/json" };
      if (token) headers["X-TMP-MCP-Admin-Token"] = token;
      const response = await fetch(path, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      const textBody = await response.text();
      let parsed;
      try { parsed = JSON.parse(textBody); }
      catch { parsed = { ok: false, summary: textBody || response.statusText }; }
      parsed.http_status = response.status;
      if (!response.ok && parsed.ok !== false) parsed.ok = false;
      return parsed;
    }
    async function validatePatch() {
      try {
        setActionResult(await callGateway("/api/config/validate", {
          config_patch: parseJsonField("configPatch") || {},
        }));
      } catch (error) {
        setActionResult({ ok: false, summary: "config validation request failed", data: { error: String(error) } });
      }
    }
    async function updatePatch() {
      try {
        const result = await callGateway("/api/config/update", {
          config_patch: parseJsonField("configPatch") || {},
          admin_approver: document.getElementById("adminApprover").value.trim(),
          admin_identity_assertion: parseJsonField("adminAssertion"),
          change_reason: "submitted from hosted B/S config admin",
        });
        setActionResult(result);
        if (result.ok) window.setTimeout(() => window.location.reload(), 700);
      } catch (error) {
        setActionResult({ ok: false, summary: "config update request failed", data: { error: String(error) } });
      }
    }
    document.getElementById("validatePatch").addEventListener("click", validatePatch);
    document.getElementById("updatePatch").addEventListener("click", updatePatch);
  </script>
</body>
</html>
"""
