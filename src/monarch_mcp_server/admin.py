"""
Admin routes for the Monarch MCP Server (remote mode).

Provides:
- /admin/status: Token health status page (password protected)
- /admin/reauth: Monarch Money re-authentication web form (password protected)

These routes are mounted as custom Starlette routes on the FastMCP server
when running in streamable-http mode.
"""

import logging
import os
import secrets
from typing import Optional

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

logger = logging.getLogger(__name__)

MCP_AUTH_PASSWORD_ENV = "MCP_AUTH_PASSWORD"

# ---------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------

_BASE_STYLES = """
    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #1a1a2e;
        color: #e0e0e0;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        margin: 0;
    }
    .container {
        background: #16213e;
        border-radius: 12px;
        padding: 2rem;
        max-width: 450px;
        width: 90%;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    h1 {
        font-size: 1.4rem;
        margin: 0 0 0.5rem 0;
        color: #4ecca3;
    }
    h2 {
        font-size: 1.1rem;
        margin: 0 0 1rem 0;
        color: #b0b0c0;
        font-weight: normal;
    }
    p {
        font-size: 0.9rem;
        color: #a0a0b0;
        margin: 0 0 1rem 0;
    }
    label {
        display: block;
        font-size: 0.85rem;
        margin-bottom: 0.4rem;
        color: #b0b0c0;
    }
    input[type="text"],
    input[type="password"],
    input[type="email"] {
        width: 100%;
        padding: 0.7rem;
        border: 1px solid #2a2a4a;
        border-radius: 8px;
        background: #0f0f23;
        color: #e0e0e0;
        font-size: 1rem;
        box-sizing: border-box;
        margin-bottom: 1rem;
    }
    input:focus {
        outline: none;
        border-color: #4ecca3;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background: #4ecca3;
        color: #1a1a2e;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        font-weight: 600;
        cursor: pointer;
    }
    button:hover {
        background: #3dba8f;
    }
    .error {
        background: rgba(239, 68, 68, 0.1);
        border: 1px solid rgba(239, 68, 68, 0.3);
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 1rem;
        font-size: 0.85rem;
        color: #ef4444;
    }
    .success {
        background: rgba(78, 204, 163, 0.1);
        border: 1px solid rgba(78, 204, 163, 0.3);
        border-radius: 8px;
        padding: 0.75rem;
        margin-bottom: 1rem;
        font-size: 0.85rem;
        color: #4ecca3;
    }
    .status-item {
        display: flex;
        justify-content: space-between;
        padding: 0.5rem 0;
        border-bottom: 1px solid #2a2a4a;
        font-size: 0.9rem;
    }
    .status-item:last-child {
        border-bottom: none;
    }
    .status-value {
        font-weight: 600;
    }
    .status-ok { color: #4ecca3; }
    .status-warn { color: #ffc107; }
    .status-err { color: #ef4444; }
    .nav {
        margin-top: 1.5rem;
        text-align: center;
    }
    .nav a {
        color: #4ecca3;
        text-decoration: none;
        font-size: 0.85rem;
    }
    .nav a:hover {
        text-decoration: underline;
    }
"""


def _render_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>{_BASE_STYLES}</style>
</head>
<body>
    <div class="container">
        {body}
    </div>
</body>
</html>"""


def _validate_admin_password(password: str) -> bool:
    """Validate the admin password against the configured env var."""
    expected = os.environ.get(MCP_AUTH_PASSWORD_ENV, "")
    if not expected:
        return False
    return secrets.compare_digest(password, expected)


# ---------------------------------------------------------------
# Admin password gate
# ---------------------------------------------------------------

_ADMIN_PASSWORD_FORM = """
<h1>Monarch MCP Server</h1>
<h2>Admin Access</h2>
{message}
<form method="POST" action="{action}">
    <input type="hidden" name="step" value="admin_auth">
    <label for="admin_password">Server Password</label>
    <input type="password" id="admin_password" name="admin_password" required autofocus>
    <button type="submit">Continue</button>
</form>
"""

# ---------------------------------------------------------------
# Monarch re-auth form (email/password)
# ---------------------------------------------------------------

_MONARCH_LOGIN_FORM = """
<h1>Monarch MCP Server</h1>
<h2>Re-authenticate with Monarch Money</h2>
{message}
<form method="POST" action="/admin/reauth">
    <input type="hidden" name="step" value="monarch_login">
    <input type="hidden" name="admin_token" value="{admin_token}">
    <label for="email">Monarch Email</label>
    <input type="email" id="email" name="email" required autofocus>
    <label for="password">Monarch Password</label>
    <input type="password" id="password" name="password" required>
    <button type="submit">Login to Monarch</button>
</form>
<div class="nav"><a href="/admin/status">Back to status</a></div>
"""

# ---------------------------------------------------------------
# MFA form
# ---------------------------------------------------------------

_MFA_FORM = """
<h1>Monarch MCP Server</h1>
<h2>Multi-Factor Authentication</h2>
<p>Enter the MFA code from your authenticator app.</p>
{message}
<form method="POST" action="/admin/reauth">
    <input type="hidden" name="step" value="mfa">
    <input type="hidden" name="admin_token" value="{admin_token}">
    <input type="hidden" name="email" value="{email}">
    <input type="hidden" name="password" value="{password}">
    <label for="mfa_code">MFA Code</label>
    <input type="text" id="mfa_code" name="mfa_code" required autofocus
           pattern="[0-9]*" inputmode="numeric" maxlength="6">
    <button type="submit">Verify</button>
</form>
"""


# ---------------------------------------------------------------
# Route handler functions
# ---------------------------------------------------------------

# In-memory admin session tokens (short-lived, single-use-ish)
_admin_sessions: dict[str, float] = {}


def _create_admin_token() -> str:
    """Create a short-lived admin session token."""
    import time

    token = secrets.token_urlsafe(32)
    _admin_sessions[token] = time.time()
    # Clean up old sessions (older than 10 minutes)
    cutoff = time.time() - 600
    expired = [k for k, v in _admin_sessions.items() if v < cutoff]
    for k in expired:
        del _admin_sessions[k]
    return token


def _validate_admin_token(token: str) -> bool:
    """Check if an admin session token is valid."""
    import time

    created = _admin_sessions.get(token)
    if not created:
        return False
    if time.time() - created > 600:  # 10 minute expiry
        del _admin_sessions[token]
        return False
    return True


async def handle_status_get(request: Request) -> Response:
    """GET /admin/status - show admin password form."""
    body = _ADMIN_PASSWORD_FORM.format(message="", action="/admin/status")
    return HTMLResponse(_render_page("Monarch MCP - Status", body))


async def handle_status_post(request: Request) -> Response:
    """POST /admin/status - validate password and show token status."""
    from monarch_mcp_server.secure_session import secure_session

    form = await request.form()
    password = str(form.get("admin_password", ""))

    if not _validate_admin_password(password):
        body = _ADMIN_PASSWORD_FORM.format(
            message='<div class="error">Invalid password</div>',
            action="/admin/status",
        )
        return HTMLResponse(_render_page("Monarch MCP - Status", body), status_code=401)

    # Get token status
    status = secure_session.get_token_status()

    # Build status display
    def _icon(val: bool) -> str:
        return (
            '<span class="status-ok">Active</span>'
            if val
            else '<span class="status-err">None</span>'
        )

    status_html = f"""
    <h1>Monarch MCP Server</h1>
    <h2>Token Status</h2>
    <div class="status-item">
        <span>In-Memory Token</span>
        <span class="status-value">{_icon(status["has_in_memory_token"])}</span>
    </div>
    <div class="status-item">
        <span>Last Updated</span>
        <span class="status-value">{status["in_memory_updated_at"] or '<span class="status-warn">Never</span>'}</span>
    </div>
    <div class="status-item">
        <span>Environment Variable</span>
        <span class="status-value">{_icon(status["has_env_var_token"])}</span>
    </div>
    <div class="status-item">
        <span>Keyring Available</span>
        <span class="status-value">{_icon(status["keyring_available"])}</span>
    </div>
    <div class="status-item">
        <span>Keyring Token</span>
        <span class="status-value">{_icon(status["has_keyring_token"])}</span>
    </div>
    <div class="status-item" style="margin-top: 0.5rem; border-top: 2px solid #2a2a4a; padding-top: 0.75rem;">
        <span><strong>Overall</strong></span>
        <span class="status-value">{'<span class="status-ok">Token Available</span>' if status["has_any_token"] else '<span class="status-err">No Token - Re-auth Required</span>'}</span>
    </div>
    <div class="nav" style="margin-top: 1.5rem;">
        <a href="/admin/reauth">Re-authenticate with Monarch Money</a>
    </div>
    """
    return HTMLResponse(_render_page("Monarch MCP - Status", status_html))


async def handle_reauth_get(request: Request) -> Response:
    """GET /admin/reauth - show admin password form."""
    body = _ADMIN_PASSWORD_FORM.format(message="", action="/admin/reauth")
    return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))


async def handle_reauth_post(request: Request) -> Response:
    """POST /admin/reauth - multi-step re-authentication flow."""
    from monarchmoney import MonarchMoney, RequireMFAException

    from monarch_mcp_server.secure_session import secure_session

    form = await request.form()
    step = str(form.get("step", "admin_auth"))

    # ---------------------------------------------------------------
    # Step 1: Validate admin password
    # ---------------------------------------------------------------
    if step == "admin_auth":
        password = str(form.get("admin_password", ""))
        if not _validate_admin_password(password):
            body = _ADMIN_PASSWORD_FORM.format(
                message='<div class="error">Invalid password</div>',
                action="/admin/reauth",
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=401
            )

        # Create admin session token for subsequent steps
        admin_token = _create_admin_token()
        body = _MONARCH_LOGIN_FORM.format(message="", admin_token=admin_token)
        return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))

    # ---------------------------------------------------------------
    # Step 2: Monarch login (email/password)
    # ---------------------------------------------------------------
    if step == "monarch_login":
        admin_token = str(form.get("admin_token", ""))
        if not _validate_admin_token(admin_token):
            body = _ADMIN_PASSWORD_FORM.format(
                message='<div class="error">Session expired. Please start over.</div>',
                action="/admin/reauth",
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=401
            )

        email = str(form.get("email", ""))
        password = str(form.get("password", ""))

        if not email or not password:
            body = _MONARCH_LOGIN_FORM.format(
                message='<div class="error">Email and password are required.</div>',
                admin_token=admin_token,
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=400
            )

        try:
            mm = MonarchMoney()
            await mm.login(
                email=email,
                password=password,
                use_saved_session=False,
                save_session=False,
            )

            # Login succeeded without MFA
            if mm.token:
                secure_session.update_token_in_memory(mm.token)
                logger.info("Monarch re-auth succeeded (no MFA)")
                body = f"""
                <h1>Monarch MCP Server</h1>
                <div class="success">Monarch Money authentication successful! Token updated.</div>
                <p>The server is now using the new token. It will persist until the server restarts.</p>
                <div class="nav"><a href="/admin/status">View token status</a></div>
                """
                return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))
            else:
                body = _MONARCH_LOGIN_FORM.format(
                    message='<div class="error">Login succeeded but no token was returned.</div>',
                    admin_token=admin_token,
                )
                return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))

        except RequireMFAException:
            # MFA is required - show MFA form
            logger.info("Monarch login requires MFA, showing MFA form")
            body = _MFA_FORM.format(
                message="",
                admin_token=admin_token,
                email=email,
                password=password,
            )
            return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))

        except Exception as e:
            logger.error(f"Monarch login failed: {e}")
            body = _MONARCH_LOGIN_FORM.format(
                message=f'<div class="error">Login failed: {str(e)}</div>',
                admin_token=admin_token,
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=401
            )

    # ---------------------------------------------------------------
    # Step 3: MFA verification
    # ---------------------------------------------------------------
    if step == "mfa":
        admin_token = str(form.get("admin_token", ""))
        if not _validate_admin_token(admin_token):
            body = _ADMIN_PASSWORD_FORM.format(
                message='<div class="error">Session expired. Please start over.</div>',
                action="/admin/reauth",
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=401
            )

        email = str(form.get("email", ""))
        password = str(form.get("password", ""))
        mfa_code = str(form.get("mfa_code", ""))

        if not mfa_code:
            body = _MFA_FORM.format(
                message='<div class="error">MFA code is required.</div>',
                admin_token=admin_token,
                email=email,
                password=password,
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=400
            )

        try:
            mm = MonarchMoney()
            await mm.multi_factor_authenticate(
                email=email,
                password=password,
                code=mfa_code,
            )

            if mm.token:
                secure_session.update_token_in_memory(mm.token)
                logger.info("Monarch re-auth succeeded (with MFA)")
                body = f"""
                <h1>Monarch MCP Server</h1>
                <div class="success">Monarch Money authentication successful! Token updated.</div>
                <p>The server is now using the new token. It will persist until the server restarts.</p>
                <div class="nav"><a href="/admin/status">View token status</a></div>
                """
                return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))
            else:
                body = _MFA_FORM.format(
                    message='<div class="error">MFA succeeded but no token was returned.</div>',
                    admin_token=admin_token,
                    email=email,
                    password=password,
                )
                return HTMLResponse(_render_page("Monarch MCP - Re-auth", body))

        except Exception as e:
            logger.error(f"Monarch MFA failed: {e}")
            body = _MFA_FORM.format(
                message=f'<div class="error">MFA failed: {str(e)}</div>',
                admin_token=admin_token,
                email=email,
                password=password,
            )
            return HTMLResponse(
                _render_page("Monarch MCP - Re-auth", body), status_code=401
            )

    # Unknown step
    body = _ADMIN_PASSWORD_FORM.format(
        message='<div class="error">Invalid request.</div>',
        action="/admin/reauth",
    )
    return HTMLResponse(_render_page("Monarch MCP - Re-auth", body), status_code=400)
