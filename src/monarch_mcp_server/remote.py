"""Remote server configuration for Streamable HTTP mode with OAuth 2.1.

Contains:
- _configure_remote_auth(): Sets up OAuth provider, login routes, admin routes
- _run_remote_server(): Launches uvicorn with security middleware
- _LOGIN_BODY: HTML template for the OAuth consent/login page
"""

import logging
import os

logger = logging.getLogger(__name__)


_LOGIN_BODY = """
<h1>Monarch MCP Server</h1>
<p>Authorize Claude to access your Monarch Money data.</p>
<div class="warning">
    Only approve this if you initiated the connection from claude.ai.
</div>
{error_html}
<form method="POST" action="/auth/login">
    <input type="hidden" name="session" value="{session}">
    <label for="password">Server Password</label>
    <input type="password" id="password" name="password" required autofocus>
    <button type="submit">Authorize</button>
</form>
"""


def _configure_remote_auth(mcp):
    """Configure OAuth auth provider and login routes for remote/HTTP mode."""
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, RedirectResponse, Response

    from mcp.server.auth.settings import (
        AuthSettings,
        ClientRegistrationOptions,
        RevocationOptions,
    )
    from pydantic import AnyHttpUrl

    from monarch_mcp_server.oauth import MonarchOAuthProvider
    from monarch_mcp_server.security import (
        admin_rate_limiter,
        auth_rate_limiter,
        get_client_ip,
        log_auth_event,
        rate_limit,
    )

    server_url = os.environ.get("MCP_SERVER_URL", "")
    if not server_url:
        logger.warning(
            "MCP_SERVER_URL not set. OAuth metadata endpoints will not work correctly. "
            "Set this to your public Railway URL (e.g., https://monarch-mcp-server.up.railway.app)"
        )
        server_url = "http://localhost:8000"

    # Create the OAuth provider
    oauth_provider = MonarchOAuthProvider()

    # Configure FastMCP with auth
    mcp.settings.auth = AuthSettings(
        issuer_url=AnyHttpUrl(server_url),
        resource_server_url=AnyHttpUrl(server_url),
        client_registration_options=ClientRegistrationOptions(enabled=False),
        revocation_options=RevocationOptions(enabled=True),
    )
    mcp._auth_server_provider = oauth_provider

    # The SDK auto-creates a ProviderTokenVerifier from the auth_server_provider
    from mcp.server.auth.provider import ProviderTokenVerifier

    mcp._token_verifier = ProviderTokenVerifier(oauth_provider)

    # ---------------------------------------------------------------
    # Custom routes: /auth/login (GET = form, POST = submit)
    # ---------------------------------------------------------------

    from monarch_mcp_server.admin import _render_page

    @mcp.custom_route("/auth/login", methods=["GET"])
    async def auth_login_get(request: Request) -> Response:
        """Render the password gate login form."""
        session = request.query_params.get("session", "")
        if not session:
            return HTMLResponse(
                "<h1>400 Bad Request</h1><p>Missing session parameter.</p>",
                status_code=400,
            )
        body = _LOGIN_BODY.format(session=session, error_html="")
        return HTMLResponse(_render_page("Monarch MCP - Authorize", body))

    @mcp.custom_route("/auth/login", methods=["POST"])
    @rate_limit(auth_rate_limiter)
    async def auth_login_post(request: Request) -> Response:
        """Handle password submission and complete authorization."""
        form = await request.form()
        session_id = form.get("session", "")
        password = form.get("password", "")
        client_ip = get_client_ip(request)

        if not session_id or not password:
            return HTMLResponse(
                "<h1>400 Bad Request</h1><p>Missing session or password.</p>",
                status_code=400,
            )

        try:
            redirect_url = oauth_provider.complete_authorization(
                str(session_id), str(password)
            )
            log_auth_event("oauth_consent", client_ip=client_ip, success=True)
            return RedirectResponse(url=redirect_url, status_code=302)
        except ValueError as e:
            log_auth_event(
                "oauth_consent",
                client_ip=client_ip,
                success=False,
                details=str(e),
            )
            error_html = f'<div class="error">{str(e)}</div>'
            body = _LOGIN_BODY.format(session=session_id, error_html=error_html)
            return HTMLResponse(
                _render_page("Monarch MCP - Authorize", body), status_code=401
            )

    # ---------------------------------------------------------------
    # Admin routes: /admin/status and /admin/reauth
    # ---------------------------------------------------------------

    from monarch_mcp_server.admin import (
        handle_reauth_get,
        handle_reauth_post,
        handle_status_get,
        handle_status_post,
    )

    @mcp.custom_route("/admin/status", methods=["GET"])
    async def admin_status_get(request: Request) -> Response:
        return await handle_status_get(request)

    @mcp.custom_route("/admin/status", methods=["POST"])
    @rate_limit(admin_rate_limiter)
    async def admin_status_post(request: Request) -> Response:
        return await handle_status_post(request)

    @mcp.custom_route("/admin/reauth", methods=["GET"])
    async def admin_reauth_get(request: Request) -> Response:
        return await handle_reauth_get(request)

    @mcp.custom_route("/admin/reauth", methods=["POST"])
    @rate_limit(admin_rate_limiter)
    async def admin_reauth_post(request: Request) -> Response:
        return await handle_reauth_post(request)

    logger.info("OAuth auth provider, login routes, and admin routes configured")


def _run_remote_server(mcp):
    """Run the MCP server in streamable-http mode with security middleware."""
    import anyio
    import uvicorn

    from monarch_mcp_server.security import OriginValidationMiddleware

    async def _serve():
        # Build the Starlette app from FastMCP
        starlette_app = mcp.streamable_http_app()

        # Wrap with Origin validation middleware
        starlette_app = OriginValidationMiddleware(starlette_app)

        config = uvicorn.Config(
            starlette_app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()

    try:
        anyio.run(_serve)
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise
