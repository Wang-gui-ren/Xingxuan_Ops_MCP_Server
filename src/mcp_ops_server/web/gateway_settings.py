from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


GATEWAY_SETTINGS_SCHEMA_VERSION = "gateway-settings-console-v1"


def build_gateway_settings_bundle(
    *,
    options_state: dict[str, Any],
    routes_state: dict[str, Any],
    include_html: bool = True,
) -> dict[str, Any]:
    state = {
        "schema_version": GATEWAY_SETTINGS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "options": dict(options_state),
        "routes": dict(routes_state),
        "design_notes": {
            "style": "semi_design",
            "layout": "semi design admin console",
            "component_basis": "Card, Form, RadioGroup button, Switch, Button, Tag",
            "mutation_guard": "X-TMP-MCP-Admin-Token",
        },
    }
    bundle = {
        "schema_version": GATEWAY_SETTINGS_SCHEMA_VERSION,
        "generated_at": state["generated_at"],
        "design_system": _design_system(),
        "state": state,
    }
    if include_html:
        bundle["html"] = _render_html(state)
    return bundle


def _design_system() -> dict[str, Any]:
    return {
        "name": "tmp-mcp-semi-design-gateway-settings",
        "palette": {
            "background": "#f5f6fa",
            "surface": "#ffffff",
            "sidebar": "#ffffff",
            "ink": "#1c1f23",
            "muted": "#646a73",
            "line": "#dee0e3",
            "primary": "#0064fa",
            "secondary": "#3370ff",
            "success": "#00a870",
            "warning": "#f5a623",
            "danger": "#f93920",
        },
        "radius_px": 6,
        "font_stack": "Inter, Segoe UI, system-ui, sans-serif",
        "mono_stack": "Fira Code, Consolas, ui-monospace, monospace",
        "semi_mcp": {
            "purpose": "development-time component documentation lookup",
            "server_name": "semi-mcp",
            "command": "npx",
            "args": ["-y", "@douyinfe/semi-mcp"],
            "intranet_package": "@ies/semi-mcp-bytedance",
        },
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
  <title>星璇运维MCP 网关设置</title>
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
    button, input, select, textarea { font: inherit; }
    button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 3px solid rgba(0, 100, 250, 0.22);
      outline-offset: 2px;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
    }
    .semi-design-shell {
      background:
        linear-gradient(180deg, rgba(232, 243, 255, 0.65) 0, rgba(245, 246, 250, 0) 270px),
        var(--bg);
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      padding: 16px 12px;
      gap: 16px;
    }
    .side-brand {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 8px 8px;
      min-width: 0;
    }
    .brand-mark {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      color: #fff;
      background: linear-gradient(135deg, var(--primary), #18a0c9);
      font-weight: 800;
      flex: 0 0 auto;
    }
    .side-brand h1 {
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
    .content {
      min-width: 0;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 4;
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 14px;
      align-items: center;
      padding: 14px 20px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
    }
    .topbar h2 {
      margin: 0;
      font-size: 17px;
      line-height: 1.15;
      letter-spacing: 0;
    }
    .topbar p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
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
      min-height: 42px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--semi-color-bg-2, #fff);
    }
    .panel-head h3 {
      margin: 0;
      font-size: 13px;
      letter-spacing: 0;
    }
    .panel-body { padding: 14px; }
    .metrics {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      min-height: 72px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
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
      font-size: 20px;
      line-height: 1;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
      gap: 10px;
    }
    .field {
      display: grid;
      gap: 6px;
      min-width: 0;
    }
    label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    input[type="password"] {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-bg-0, #fff);
      color: var(--ink);
      padding: 7px 11px;
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }
    input[type="password"]:hover { border-color: var(--primary); }
    input[type="password"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(0, 100, 250, 0.12);
    }
    .segmented {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0;
      padding: 2px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-fill-0, #f7f8fa);
    }
    .segment {
      min-width: 0;
      cursor: pointer;
    }
    .segment input,
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .segment span {
      min-height: 32px;
      display: grid;
      place-items: center;
      border-radius: 5px;
      color: var(--semi-color-text-1, #373c43);
      font-size: 12px;
      font-weight: 600;
      transition: background 160ms ease, color 160ms ease, box-shadow 160ms ease;
    }
    .segment input:checked + span {
      background: var(--semi-color-bg-2, #fff);
      color: var(--primary);
      box-shadow: 0 2px 6px rgba(31, 35, 41, 0.1);
    }
    .segment input:focus-visible + span {
      outline: 3px solid rgba(0, 100, 250, 0.22);
      outline-offset: 2px;
    }
    .toggle-list {
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 8px;
    }
    .switch-card {
      width: 100%;
      min-width: 0;
      min-height: 62px;
      height: auto;
      box-sizing: border-box;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 44px;
      align-items: center;
      justify-self: stretch;
      gap: 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 11px 12px;
      background: var(--semi-color-bg-2, #fff);
      cursor: pointer;
      transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
    }
    .switch-card.semi-switch {
      width: 100%;
      min-width: 0;
      max-width: none;
      height: auto;
      min-height: 62px;
    }
    .switch-card:hover {
      border-color: rgba(0, 100, 250, 0.35);
      background: var(--semi-color-primary-light-default, #f0f7ff);
      box-shadow: 0 2px 8px rgba(31, 35, 41, 0.06);
    }
    .switch-copy {
      min-width: 0;
      display: block;
    }
    .switch-title {
      display: block;
      font-size: 12px;
      line-height: 1.2;
      font-weight: 700;
      word-break: keep-all;
      white-space: nowrap;
    }
    .switch-desc {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      word-break: normal;
      overflow-wrap: anywhere;
    }
    .switch-track {
      position: relative;
      justify-self: end;
      flex: 0 0 auto;
      width: 42px;
      height: 22px;
      border-radius: 999px;
      background: var(--semi-color-disabled-fill, #c9cdd4);
      box-shadow: inset 0 0 0 1px rgba(31, 35, 41, 0.08);
      transition: background 160ms ease, box-shadow 160ms ease;
    }
    .switch-track::after {
      content: "";
      position: absolute;
      top: 2px;
      left: 2px;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 1px 3px rgba(31, 35, 41, 0.3);
      transition: transform 160ms ease;
    }
    .switch-input:checked + .switch-track {
      background: var(--primary);
    }
    .switch-input:checked + .switch-track::after {
      transform: translateX(20px);
    }
    .switch-input:focus-visible + .switch-track {
      outline: 3px solid rgba(0, 100, 250, 0.22);
      outline-offset: 2px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .btn {
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-bg-2, #fff);
      color: var(--ink);
      padding: 7px 12px;
      cursor: pointer;
      font-weight: 600;
      text-transform: none;
      transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }
    .btn:hover { border-color: var(--primary); color: var(--primary); }
    .btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .btn.primary:hover { background: var(--primary-hover); border-color: var(--primary-hover); color: #fff; }
    .btn svg { width: 15px; height: 15px; flex: 0 0 auto; }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      padding: 3px 8px;
      color: var(--muted);
      background: var(--semi-color-fill-0, #f7f8fa);
      font-size: 12px;
      white-space: nowrap;
    }
    .status.on {
      color: var(--semi-color-success, #00a870);
      background: var(--semi-color-success-light-default, #e9f8f3);
      border-color: transparent;
    }
    .status.warn {
      color: var(--semi-color-warning, #f5a623);
      background: var(--semi-color-warning-light-default, #fff7e6);
      border-color: transparent;
    }
    .status.off {
      color: var(--semi-color-danger, #f93920);
      background: var(--semi-color-danger-light-default, #fff0ed);
      border-color: transparent;
    }
    pre {
      margin: 0;
      max-height: 280px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--semi-color-fill-0, #f7f8fa);
      color: var(--ink);
      padding: 10px;
      font: 11px/1.45 "Fira Code", Consolas, ui-monospace, monospace;
    }
    .route-list {
      display: grid;
      gap: 8px;
    }
    .route {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 8px 0;
      border-bottom: 1px solid var(--soft-line);
    }
    .route:last-child { border-bottom: 0; }
    .route span { color: var(--muted); font-size: 12px; }
    .route code { overflow-wrap: anywhere; font: 12px Consolas, ui-monospace, monospace; }
    @media (max-width: 1040px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .side-footer { display: none; }
      .layout { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .topbar { grid-template-columns: 1fr; align-items: start; }
      .chips { justify-content: flex-start; }
      .layout { padding: 10px; }
      .metrics, .form-grid, .nav { grid-template-columns: 1fr; }
      .route { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <script type="application/json" id="gateway-settings-state">__STATE_JSON__</script>
  <div class="app astrbot-like-shell semi-design-shell" data-ui-style="semi_design" data-design-system="semi-design">
    <aside class="sidebar semi-navigation" data-semi-component="Navigation">
      <div class="side-brand">
        <div class="brand-mark" aria-hidden="true">星</div>
        <div>
          <h1>星璇运维MCP</h1>
          <p data-i18n="settings.brand.subtitle">审批与配置控制台</p>
        </div>
      </div>
      <nav class="nav" aria-label="Gateway pages">
        <a class="semi-navigation-item" href="/approvals">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l7 3v5c0 5-3.2 8.3-7 10-3.8-1.7-7-5-7-10V6l7-3z"></path><path d="M9 12l2 2 4-5"></path></svg>
          <span data-i18n="nav.approvals">审批台</span>
        </a>
        <a class="semi-navigation-item" href="/config-admin">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5z"></path><path d="M19.4 15a1.8 1.8 0 0 0 .36 1.98l.04.04a2 2 0 1 1-2.83 2.83l-.04-.04A1.8 1.8 0 0 0 15 19.4a1.8 1.8 0 0 0-1 .6V20a2 2 0 1 1-4 0v-.06a1.8 1.8 0 0 0-1-.54 1.8 1.8 0 0 0-1.98.36l-.04.04a2 2 0 1 1-2.83-2.83l.04-.04A1.8 1.8 0 0 0 4.6 15a1.8 1.8 0 0 0-.6-1H4a2 2 0 1 1 0-4h.06a1.8 1.8 0 0 0 .54-1 1.8 1.8 0 0 0-.36-1.98l-.04-.04a2 2 0 1 1 2.83-2.83l.04.04A1.8 1.8 0 0 0 9 4.6a1.8 1.8 0 0 0 1-.6V4a2 2 0 1 1 4 0v.06a1.8 1.8 0 0 0 1 .54 1.8 1.8 0 0 0 1.98-.36l.04-.04a2 2 0 1 1 2.83 2.83l-.04.04A1.8 1.8 0 0 0 19.4 9c.2.36.4.7.6 1H20a2 2 0 1 1 0 4h-.06c-.14.35-.32.68-.54 1z"></path></svg>
          <span data-i18n="nav.config">配置管理</span>
        </a>
        <a class="active semi-navigation-item semi-navigation-item-selected" href="/gateway-settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16"></path><path d="M4 12h16"></path><path d="M4 18h16"></path><path d="M8 6v4"></path><path d="M16 12v4"></path></svg>
          <span data-i18n="nav.settings">网关设置</span>
        </a>
      </nav>
      <div class="side-footer">
        <span data-i18n="settings.footer">选项只写入 tmp_MCP 项目内配置，并由本地托管网关生效。</span>
      </div>
    </aside>

    <main class="content">
      <header class="topbar">
        <div>
          <h2 data-i18n="settings.title">网关控制选项</h2>
          <p id="generatedAt"></p>
        </div>
        <div class="top-actions">
          <div class="locale-switch" role="tablist" aria-label="Language">
            <button type="button" data-locale="zh" class="active">中文</button>
            <button type="button" data-locale="en">EN</button>
          </div>
          <div class="chips" id="chips"></div>
        </div>
      </header>

      <section class="layout">
        <div class="stack">
          <article class="panel semi-card" data-semi-component="Card">
            <div class="panel-head"><h3 data-i18n="settings.runtime">运行状态</h3><span class="status semi-tag" id="runtimeStatus"></span></div>
            <div class="panel-body"><div class="metrics" id="metrics"></div></div>
          </article>
          <article class="panel semi-card" data-semi-component="Form">
            <div class="panel-head"><h3 data-i18n="settings.ui_options">界面选项</h3><span class="status semi-tag on">Semi Form</span></div>
            <div class="panel-body">
              <div class="form-grid">
                <div class="field">
                  <label for="defaultPage">default_page</label>
                  <div class="segmented semi-radioGroup semi-radio-button-group" id="defaultPage" data-control="default_page" data-semi-component="RadioGroup" role="radiogroup" aria-label="Default page">
                    <label class="segment semi-radio-button"><input type="radio" name="defaultPage" value="approvals" /><span data-i18n="nav.approvals">审批台</span></label>
                    <label class="segment semi-radio-button"><input type="radio" name="defaultPage" value="config-admin" /><span data-i18n="nav.config_short">配置</span></label>
                  </div>
                </div>
                <div class="field">
                  <label for="uiStyle">style</label>
                  <div class="segmented semi-radioGroup semi-radio-button-group" id="uiStyle" data-control="style" data-semi-component="RadioGroup" role="radiogroup" aria-label="UI style">
                    <label class="segment semi-radio-button"><input type="radio" name="uiStyle" value="semi_design" /><span>Semi</span></label>
                    <label class="segment semi-radio-button"><input type="radio" name="uiStyle" value="tmp_mcp" /><span>星璇经典</span></label>
                  </div>
                </div>
                <div class="field">
                  <label for="density">density</label>
                  <div class="segmented semi-radioGroup semi-radio-button-group" id="density" data-control="density" data-semi-component="RadioGroup" role="radiogroup" aria-label="Density">
                    <label class="segment semi-radio-button"><input type="radio" name="density" value="compact" /><span>Compact</span></label>
                    <label class="segment semi-radio-button"><input type="radio" name="density" value="comfortable" /><span>Comfort</span></label>
                  </div>
                </div>
                <div class="field">
                  <label for="gatewayToken">gateway_admin_token</label>
                  <input class="semi-input" id="gatewayToken" type="password" autocomplete="off" placeholder="required for validate/update" />
                </div>
              </div>
            </div>
          </article>
          <article class="panel semi-card" data-semi-component="Switch">
            <div class="panel-head"><h3 data-i18n="settings.feature_switches">功能开关</h3><span class="status semi-tag" id="featureStatus"></span></div>
            <div class="panel-body"><div class="toggle-list" id="featureToggles"></div></div>
          </article>
        </div>

        <div class="stack">
          <article class="panel semi-card" data-semi-component="Button">
            <div class="panel-head"><h3 data-i18n="settings.submit">提交</h3><span class="status semi-tag" id="submitStatus">idle</span></div>
            <div class="panel-body">
              <div class="actions">
                <button class="btn semi-button" type="button" id="validateBtn">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"></path></svg>
                  <span data-i18n="action.validate">校验</span>
                </button>
                <button class="btn primary semi-button semi-button-primary" type="button" id="updateBtn">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path></svg>
                  <span data-i18n="action.update">更新</span>
                </button>
              </div>
            </div>
          </article>
          <article class="panel semi-card" data-semi-component="Card">
            <div class="panel-head"><h3 data-i18n="settings.preview">开发者预览</h3><span class="status semi-tag">json</span></div>
            <div class="panel-body"><pre id="patchPreview">{}</pre></div>
          </article>
          <article class="panel semi-card" data-semi-component="Card">
            <div class="panel-head"><h3 data-i18n="settings.result">网关结果</h3><span class="status semi-tag" id="resultStatus">empty</span></div>
            <div class="panel-body"><pre id="resultJson">{}</pre></div>
          </article>
          <article class="panel semi-card" data-semi-component="Card">
            <div class="panel-head"><h3 data-i18n="settings.routes">路由</h3><span class="status semi-tag" id="routeCount"></span></div>
            <div class="panel-body"><div class="route-list" id="routeList"></div></div>
          </article>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = JSON.parse(document.getElementById("gateway-settings-state").textContent);
    const options = state.options || {};
    const effective = options.effective_config || {};
    const routes = state.routes && state.routes.routes ? state.routes.routes : {};
    let locale = localStorage.getItem("tmp_mcp_ui_locale") || "zh";
    const i18n = {
      zh: {
        "settings.brand.subtitle": "审批与配置控制台",
        "nav.approvals": "审批台",
        "nav.config": "配置管理",
        "nav.config_short": "配置",
        "nav.settings": "网关设置",
        "settings.footer": "选项只写入 tmp_MCP 项目内配置，并由本地托管网关生效。",
        "settings.title": "星璇网关控制选项",
        "settings.generated": "生成时间",
        "settings.runtime": "运行状态",
        "settings.ui_options": "界面选项",
        "settings.feature_switches": "功能开关",
        "settings.submit": "提交",
        "settings.preview": "开发者预览",
        "settings.result": "网关结果",
        "settings.routes": "路由",
        "action.validate": "校验",
        "action.update": "更新",
        "status.write_enabled": "写入已启用",
        "status.read_only": "只读",
        "status.on": "开",
        "status.off": "关",
        "status.ok": "成功",
        "status.attention": "注意",
        "status.empty": "空",
        "status.pending": "请求处理中",
        "status.enabled_count": "已开启",
        "unit.routes": "条路由",
        "feature.enable_approval_console.title": "审批控制台",
        "feature.enable_approval_console.desc": "开放人工审批操作页。",
        "feature.enable_config_admin_console.title": "配置管理台",
        "feature.enable_config_admin_console.desc": "开放身份可信配置页。",
        "feature.enable_read_apis.title": "只读 JSON API",
        "feature.enable_read_apis.desc": "向外部 B/S 壳层暴露 bundle JSON API。",
        "feature.enable_mutation_apis.title": "写入 API",
        "feature.enable_mutation_apis.desc": "允许托管页面调用受保护写接口。",
        "feature.show_gateway_settings.title": "网关设置页",
        "feature.show_gateway_settings.desc": "开放当前网关选项控制台。",
        "feature.show_api_index.title": "API 索引",
        "feature.show_api_index.desc": "开放路由索引接口。",
        "feature.require_admin_token_for_mutation.title": "要求管理员令牌",
        "feature.require_admin_token_for_mutation.desc": "保持所有 POST 写操作受网关管理员令牌保护。"
      },
      en: {
        "settings.brand.subtitle": "approval and config console",
        "nav.approvals": "Approvals",
        "nav.config": "Config Admin",
        "nav.config_short": "Config",
        "nav.settings": "Gateway Settings",
        "settings.footer": "Options are stored in the tmp_MCP project config and applied by the local hosted gateway.",
        "settings.title": "Xingxuan Gateway Control Options",
        "settings.generated": "Generated",
        "settings.runtime": "Runtime State",
        "settings.ui_options": "UI Options",
        "settings.feature_switches": "Feature Switches",
        "settings.submit": "Submit",
        "settings.preview": "Developer Preview",
        "settings.result": "Gateway Result",
        "settings.routes": "Routes",
        "action.validate": "Validate",
        "action.update": "Update",
        "status.write_enabled": "write enabled",
        "status.read_only": "read only",
        "status.on": "on",
        "status.off": "off",
        "status.ok": "ok",
        "status.attention": "attention",
        "status.empty": "empty",
        "status.pending": "request pending",
        "status.enabled_count": "enabled",
        "unit.routes": "route(s)",
        "feature.enable_approval_console.title": "Approval console",
        "feature.enable_approval_console.desc": "Open the manual approval operation page.",
        "feature.enable_config_admin_console.title": "Config admin console",
        "feature.enable_config_admin_console.desc": "Open the identity configuration page.",
        "feature.enable_read_apis.title": "Read JSON APIs",
        "feature.enable_read_apis.desc": "Expose bundle JSON APIs for external B/S shells.",
        "feature.enable_mutation_apis.title": "Mutation APIs",
        "feature.enable_mutation_apis.desc": "Allow hosted pages to call protected write endpoints.",
        "feature.show_gateway_settings.title": "Gateway settings",
        "feature.show_gateway_settings.desc": "Expose this options console.",
        "feature.show_api_index.title": "API index",
        "feature.show_api_index.desc": "Expose the route index endpoint.",
        "feature.require_admin_token_for_mutation.title": "Require admin token",
        "feature.require_admin_token_for_mutation.desc": "Keep POST writes behind the gateway admin token."
      }
    };
    const features = [
      "enable_approval_console",
      "enable_config_admin_console",
      "enable_read_apis",
      "enable_mutation_apis",
      "show_gateway_settings",
      "show_api_index"
    ];
    const gatewaySwitchKeys = [...features, "require_admin_token_for_mutation"];
    const $ = (id) => document.getElementById(id);
    const pretty = (value) => JSON.stringify(value || {}, null, 2);
    const tr = (key) => (i18n[locale] && i18n[locale][key]) || (i18n.en && i18n.en[key]) || key;

    function init() {
      setSegment("defaultPage", effective.default_page || "approvals");
      setSegment("uiStyle", effective.ui_style || "semi_design");
      setSegment("density", effective.density || "compact");
      bindLocale();
      applyLocale();
      renderChrome();
      renderFeatures();
      renderRoutes();
      bindEvents();
      renderPatch();
    }

    function bindLocale() {
      document.querySelectorAll("[data-locale]").forEach((button) => {
        button.addEventListener("click", () => {
          locale = button.dataset.locale || "zh";
          localStorage.setItem("tmp_mcp_ui_locale", locale);
          applyLocale();
          renderChrome();
          renderFeatures();
          renderRoutes();
          renderPatch();
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
      $("generatedAt").textContent = `${tr("settings.generated")} ${state.generated_at || ""}`;
    }

    function renderChrome() {
      const mutationOn = Boolean(effective.enable_mutation_apis);
      $("runtimeStatus").className = `status semi-tag ${mutationOn ? "on" : "off"}`;
      $("runtimeStatus").textContent = mutationOn ? tr("status.write_enabled") : tr("status.read_only");
      $("chips").innerHTML = [
        ["schema", state.schema_version],
        ["style", effective.ui_style || "-"],
        ["density", effective.density || "-"],
        ["config", ((options.config_paths || {}).primary_config_path || "-").split(/[\\\\/]/).pop()]
      ].map(([k, v]) => `<span class="chip semi-tag">${k}<strong>${escapeHtml(v)}</strong></span>`).join("");
      $("metrics").innerHTML = [
        ["approval", effective.enable_approval_console ? tr("status.on") : tr("status.off")],
        ["config", effective.enable_config_admin_console ? tr("status.on") : tr("status.off")],
        ["mutation", effective.enable_mutation_apis ? tr("status.on") : tr("status.off")]
      ].map(([k, v]) => `<div class="metric"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join("");
    }

    function renderFeatures() {
      $("featureToggles").innerHTML = features.map((key) => `
        <label class="switch-card semi-switch" for="${key}" data-role="gateway-switch" data-semi-component="Switch">
          <span class="switch-copy"><span class="switch-title">${tr(`feature.${key}.title`)}</span><span class="switch-desc">${tr(`feature.${key}.desc`)}</span></span>
          <input class="switch-input sr-only" type="checkbox" role="switch" aria-label="${tr(`feature.${key}.title`)}" aria-checked="${effective[key] ? "true" : "false"}" id="${key}" ${effective[key] ? "checked" : ""} />
          <span class="switch-track" aria-hidden="true"></span>
        </label>
      `).join("") + `
        <label class="switch-card semi-switch" for="require_admin_token_for_mutation" data-role="gateway-switch" data-semi-component="Switch">
          <span class="switch-copy"><span class="switch-title">${tr("feature.require_admin_token_for_mutation.title")}</span><span class="switch-desc">${tr("feature.require_admin_token_for_mutation.desc")}</span></span>
          <input class="switch-input sr-only" type="checkbox" role="switch" aria-label="${tr("feature.require_admin_token_for_mutation.title")}" aria-checked="${effective.require_admin_token_for_mutation ? "true" : "false"}" id="require_admin_token_for_mutation" ${effective.require_admin_token_for_mutation ? "checked" : ""} />
          <span class="switch-track" aria-hidden="true"></span>
        </label>
      `;
      bindFeatureEvents();
      syncSwitchAria();
      renderFeatureStatus();
    }

    function renderFeatureStatus() {
      const enabled = gatewaySwitchKeys.filter((key) => Boolean($(key) && $(key).checked)).length;
      $("featureStatus").textContent = `${enabled}/${gatewaySwitchKeys.length} ${tr("status.enabled_count")}`;
      $("featureStatus").className = `status semi-tag ${enabled ? "on" : "off"}`;
    }

    function bindFeatureEvents() {
      gatewaySwitchKeys.forEach((key) => {
        const input = $(key);
        if (input) input.addEventListener("change", renderPatch);
      });
    }

    function renderRoutes() {
      const rows = [
        ["pages", routes.pages || []],
        ["read_api", routes.read_api || []],
        ["mutation_api", routes.mutation_api || []]
      ];
      const count = rows.reduce((total, [, values]) => total + values.length, 0);
      $("routeCount").textContent = `${count} ${tr("unit.routes")}`;
      $("routeList").innerHTML = rows.map(([name, values]) => `
        <div class="route">
          <span>${escapeHtml(name)}</span>
          <code>${escapeHtml((values || []).join(", ") || "-")}</code>
        </div>
      `).join("");
    }

    function buildPatch() {
      return {
        ui: {
          default_page: segmentValue("defaultPage", "approvals"),
          style: segmentValue("uiStyle", "semi_design"),
          density: segmentValue("density", "compact")
        },
        features: Object.fromEntries(features.map((key) => [key, Boolean($(key) && $(key).checked)])),
        security: {
          require_admin_token_for_mutation: Boolean($("require_admin_token_for_mutation").checked)
        }
      };
    }

    function renderPatch() {
      syncSwitchAria();
      renderFeatureStatus();
      $("patchPreview").textContent = pretty({ config_patch: buildPatch() });
    }

    async function submit(mode) {
      const token = $("gatewayToken").value.trim();
      const headers = { "Content-Type": "application/json" };
      if (token) headers["X-TMP-MCP-Admin-Token"] = token;
      setResult({ ok: true, summary: `${mode} ${tr("status.pending")}` }, "warn");
      try {
        const response = await fetch(`/api/gateway/options/${mode}`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            config_patch: buildPatch(),
            updated_by: "gateway-settings-console",
            change_reason: "submitted from hosted B/S gateway settings"
          })
        });
        const text = await response.text();
        let payload;
        try { payload = JSON.parse(text); }
        catch { payload = { ok: false, summary: text || response.statusText }; }
        payload.http_status = response.status;
        if (!response.ok && payload.ok !== false) payload.ok = false;
        setResult(payload, payload.ok ? "on" : "warn");
        if (mode === "update" && payload.ok) {
          window.setTimeout(() => window.location.reload(), 700);
        }
      } catch (error) {
        setResult({ ok: false, summary: "gateway settings request failed", data: { error: String(error) } }, "off");
      }
    }

    function setResult(payload, cls) {
      $("submitStatus").className = `status semi-tag ${cls}`;
      $("submitStatus").textContent = payload && payload.ok ? tr("status.ok") : tr("status.attention");
      $("resultStatus").className = `status semi-tag ${cls}`;
      $("resultStatus").textContent = payload && payload.ok ? tr("status.ok") : tr("status.attention");
      $("resultJson").textContent = pretty(payload);
    }

    function bindEvents() {
      document.querySelectorAll('input[name="defaultPage"], input[name="uiStyle"], input[name="density"]').forEach((input) => {
        input.addEventListener("change", renderPatch);
      });
      $("validateBtn").addEventListener("click", () => submit("validate"));
      $("updateBtn").addEventListener("click", () => submit("update"));
    }

    function setSegment(name, value) {
      const options = Array.from(document.querySelectorAll(`input[name="${name}"]`));
      const fallback = options[0];
      const selected = options.find((input) => input.value === value) || fallback;
      if (selected) selected.checked = true;
    }

    function syncSwitchAria() {
      document.querySelectorAll('input[role="switch"]').forEach((input) => {
        input.setAttribute("aria-checked", input.checked ? "true" : "false");
      });
    }

    function segmentValue(name, fallback) {
      const selected = document.querySelector(`input[name="${name}"]:checked`);
      return selected ? selected.value : fallback;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\\"": "&quot;", "'": "&#39;"
      }[ch]));
    }

    init();
  </script>
</body>
</html>
"""
