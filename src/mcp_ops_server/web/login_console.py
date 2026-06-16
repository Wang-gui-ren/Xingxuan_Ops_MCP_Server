from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


LOGIN_CONSOLE_SCHEMA_VERSION = "login-console-bundle-v1"


def build_login_console_bundle(
    *,
    page_type: str = "login",
    include_html: bool = True,
) -> dict[str, Any]:
    """Build login/register console bundle.

    page_type: 'login' or 'register'
    """
    state = {
        "schema_version": LOGIN_CONSOLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_type": page_type,
    }
    bundle = {
        "schema_version": LOGIN_CONSOLE_SCHEMA_VERSION,
        "generated_at": state["generated_at"],
        "design_system": _design_system(),
        "state": state,
    }
    if include_html:
        bundle["html"] = _render_html(state)
    return bundle


def _design_system() -> dict[str, Any]:
    return {
        "name": "tmp-mcp-semi-design-login",
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
  <title>星璇运维MCP - 登录</title>
  <meta name="design-system" content="Semi Design" />
  <style>
    :root {
      --bg: #f5f6fa;
      --surface: #ffffff;
      --ink: #1c1f23;
      --muted: #646a73;
      --line: #dee0e3;
      --primary: #0064fa;
      --accent: #3370ff;
      --success: #00a870;
      --warning: #f5a623;
      --danger: #f93920;
      --radius: 6px;
      font-family: "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, rgba(0, 100, 250, 0.08), rgba(0, 160, 200, 0.08)), var(--bg);
      color: var(--ink);
      font-size: 14px;
    }
    .container {
      width: 100%;
      max-width: 400px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }
    .brand {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .mark {
      width: 40px;
      height: 40px;
      border-radius: 10px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, var(--primary), #00a3ff);
      color: white;
      font-weight: 800;
      font-size: 20px;
      flex-shrink: 0;
    }
    .brand-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .brand-text h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      line-height: 1.2;
    }
    .brand-text p {
      margin: 0;
      font-size: 12px;
      color: var(--muted);
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 28px;
      box-shadow: 0 2px 8px rgba(28, 31, 35, 0.08);
    }
    .panel h2 {
      margin: 0 0 20px;
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
    }
    .form {
      display: grid;
      gap: 14px;
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
    }
    .field input {
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      color: var(--ink);
      padding: 8px 12px;
      font: 13px system-ui, sans-serif;
      transition: border-color 120ms ease, box-shadow 120ms ease;
    }
    .field input:hover {
      border-color: var(--primary);
    }
    .field input:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 2px rgba(0, 100, 250, 0.12);
    }
    .error {
      padding: 8px 12px;
      border-radius: var(--radius);
      background: rgba(249, 57, 32, 0.08);
      border: 1px solid rgba(249, 57, 32, 0.25);
      color: var(--danger);
      font-size: 12px;
      display: none;
    }
    .error.show {
      display: block;
    }
    .actions {
      display: grid;
      gap: 10px;
      margin-top: 8px;
    }
    button {
      min-height: 36px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--ink);
      font: 13px system-ui, sans-serif;
      font-weight: 600;
      cursor: pointer;
      transition: all 120ms ease;
    }
    button:hover {
      border-color: var(--primary);
      color: var(--primary);
    }
    button.primary {
      border-color: var(--primary);
      background: var(--primary);
      color: white;
    }
    button.primary:hover {
      background: #0055dd;
      border-color: #0055dd;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .footer {
      text-align: center;
      font-size: 12px;
      color: var(--muted);
    }
    .footer a {
      color: var(--primary);
      text-decoration: none;
      font-weight: 600;
    }
    .footer a:hover {
      text-decoration: underline;
    }
    .status-icon {
      display: inline-block;
      width: 16px;
      height: 16px;
      margin-right: 6px;
      vertical-align: -2px;
    }
    @media (max-width: 500px) {
      .container { padding: 16px; }
      .panel { padding: 20px; }
    }
  </style>
</head>
<body>
  <script id="login-console-state" type="application/json">__STATE_JSON__</script>
  <div class="container">
    <div class="brand">
      <div class="mark">星</div>
      <div class="brand-text">
        <h1>星璇运维MCP</h1>
        <p id="brandSub">登录系统</p>
      </div>
    </div>

    <article class="panel">
      <h2 id="pageTitle">登录</h2>

      <div class="form">
        <div class="field">
          <label for="username" id="labelUsername">用户名</label>
          <input id="username" type="text" autocomplete="off" placeholder="请输入用户名" />
        </div>

        <div class="field">
          <label for="password" id="labelPassword">密码</label>
          <input id="password" type="password" autocomplete="off" placeholder="请输入密码" />
        </div>

        <div id="adminTokenField" class="field" style="display: none;">
          <label for="adminToken" id="labelAdminToken">管理员 Token</label>
          <input id="adminToken" type="password" autocomplete="off" placeholder="注册需要管理员 Token" />
        </div>

        <div id="confirmPasswordField" class="field" style="display: none;">
          <label for="confirmPassword" id="labelConfirmPassword">确认密码</label>
          <input id="confirmPassword" type="password" autocomplete="off" placeholder="请再次输入密码" />
        </div>

        <div id="errorBox" class="error" role="alert"></div>

        <div class="actions">
          <button id="submitBtn" class="primary" type="button">登录</button>
        </div>
      </div>

      <div class="footer">
        <div id="footerText"></div>
      </div>
    </article>
  </div>

  <script>
    const state = JSON.parse(document.getElementById("login-console-state").textContent);
    const pageType = state.page_type || "login";
    let isLoading = false;

    const i18n = {
      zh: {
        "brand.sub": "登录系统",
        "page.login": "登录",
        "page.register": "注册",
        "field.username": "用户名",
        "field.password": "密码",
        "field.admin_token": "管理员 Token",
        "field.confirm_password": "确认密码",
        "btn.login": "登录",
        "btn.register": "注册",
        "link.register": "没有账户？注册新账户",
        "link.login": "已有账户？返回登录",
        "error.empty_username": "请输入用户名",
        "error.empty_password": "请输入密码",
        "error.empty_admin_token": "注册需要管理员 Token",
        "error.short_password": "密码长度至少6个字符",
        "error.password_mismatch": "两次输入的密码不一致",
        "error.login_failed": "登录失败，请检查用户名和密码",
        "error.register_failed": "注册失败，请重试",
        "error.user_exists": "用户名已存在",
        "success.register": "注册成功，正在跳转...",
      },
      en: {
        "brand.sub": "Login",
        "page.login": "Login",
        "page.register": "Register",
        "field.username": "Username",
        "field.password": "Password",
        "field.admin_token": "Admin Token",
        "field.confirm_password": "Confirm Password",
        "btn.login": "Login",
        "btn.register": "Register",
        "link.register": "No account? Register now",
        "link.login": "Have account? Back to login",
        "error.empty_username": "Please enter username",
        "error.empty_password": "Please enter password",
        "error.empty_admin_token": "Admin token is required for registration",
        "error.short_password": "Password must be at least 6 characters",
        "error.password_mismatch": "Passwords do not match",
        "error.login_failed": "Login failed, please check username and password",
        "error.register_failed": "Registration failed, please try again",
        "error.user_exists": "Username already exists",
        "success.register": "Registration successful, redirecting...",
      },
    };

    let locale = localStorage.getItem("tmp_mcp_ui_locale") || "zh";
    const tr = (key) => (i18n[locale] && i18n[locale][key]) || (i18n.en && i18n.en[key]) || key;

    function setLocale(newLocale) {
      locale = newLocale;
      localStorage.setItem("tmp_mcp_ui_locale", locale);
      updateUI();
    }

    function updateUI() {
      document.getElementById("brandSub").textContent = tr("brand.sub");
      document.getElementById("pageTitle").textContent = tr(`page.${pageType}`);
      document.getElementById("labelUsername").textContent = tr("field.username");
      document.getElementById("labelPassword").textContent = tr("field.password");
      document.getElementById("labelAdminToken").textContent = tr("field.admin_token");
      document.getElementById("labelConfirmPassword").textContent = tr("field.confirm_password");

      const submitBtn = document.getElementById("submitBtn");
      submitBtn.textContent = pageType === "login" ? tr("btn.login") : tr("btn.register");

      const adminTokenField = document.getElementById("adminTokenField");
      adminTokenField.style.display = pageType === "register" ? "grid" : "none";

      const confirmField = document.getElementById("confirmPasswordField");
      confirmField.style.display = pageType === "register" ? "grid" : "none";

      const linkText = pageType === "login" ? tr("link.register") : tr("link.login");
      const linkHref = pageType === "login" ? "/register" : "/login";
      document.getElementById("footerText").innerHTML = `<a href="${linkHref}">${linkText}</a>`;
    }

    function showError(message) {
      const box = document.getElementById("errorBox");
      box.textContent = message;
      box.classList.add("show");
    }

    function clearError() {
      const box = document.getElementById("errorBox");
      box.textContent = "";
      box.classList.remove("show");
    }

    async function handleSubmit() {
      clearError();
      const username = document.getElementById("username").value.trim();
      const password = document.getElementById("password").value;

      if (!username) {
        showError(tr("error.empty_username"));
        return;
      }
      if (!password) {
        showError(tr("error.empty_password"));
        return;
      }

      if (pageType === "login") {
        await handleLogin(username, password);
      } else {
        const adminToken = document.getElementById("adminToken").value;
        const confirmPassword = document.getElementById("confirmPassword").value;
        if (!adminToken) {
          showError(tr("error.empty_admin_token"));
          return;
        }
        if (password.length < 6) {
          showError(tr("error.short_password"));
          return;
        }
        if (password !== confirmPassword) {
          showError(tr("error.password_mismatch"));
          return;
        }
        await handleRegister(username, password, adminToken);
      }
    }

    async function handleLogin(username, password) {
      if (isLoading) return;
      isLoading = true;
      document.getElementById("submitBtn").disabled = true;

      try {
        const response = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });

        const result = await response.json();
        if (result.ok) {
          localStorage.setItem("tmp_mcp_session", JSON.stringify(result.data.session));
          const redirect = localStorage.getItem("tmp_mcp_redirect") || "/approvals";
          localStorage.removeItem("tmp_mcp_redirect");
          window.location.href = redirect;
        } else {
          showError(result.summary || tr("error.login_failed"));
        }
      } catch (error) {
        showError(tr("error.login_failed"));
      } finally {
        isLoading = false;
        document.getElementById("submitBtn").disabled = false;
      }
    }

    async function handleRegister(username, password, adminToken) {
      if (isLoading) return;
      isLoading = true;
      document.getElementById("submitBtn").disabled = true;

      try {
        const response = await fetch("/api/auth/register", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-XINGXUAN-MCP-Admin-Token": adminToken,
            "X-TMP-MCP-Admin-Token": adminToken,
          },
          body: JSON.stringify({ username, password }),
        });

        const result = await response.json();
        if (result.ok) {
          localStorage.setItem("tmp_mcp_session", JSON.stringify(result.data.session));
          showError(tr("success.register"));
          setTimeout(() => {
            window.location.href = "/approvals";
          }, 700);
        } else {
          showError(result.summary || tr("error.register_failed"));
        }
      } catch (error) {
        showError(tr("error.register_failed"));
      } finally {
        isLoading = false;
        document.getElementById("submitBtn").disabled = false;
      }
    }

    document.getElementById("submitBtn").addEventListener("click", handleSubmit);
    document.getElementById("username").addEventListener("keypress", (e) => {
      if (e.key === "Enter") handleSubmit();
    });
    document.getElementById("password").addEventListener("keypress", (e) => {
      if (e.key === "Enter") handleSubmit();
    });
    document.getElementById("adminToken").addEventListener("keypress", (e) => {
      if (e.key === "Enter") handleSubmit();
    });
    document.getElementById("confirmPassword").addEventListener("keypress", (e) => {
      if (e.key === "Enter") handleSubmit();
    });

    updateUI();
  </script>
</body>
</html>
"""
