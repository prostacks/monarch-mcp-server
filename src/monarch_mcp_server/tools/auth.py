"""Authentication tools for the Monarch Money MCP Server."""

import json
import logging
import os

from monarch_mcp_server.server import mcp, run_async, get_monarch_client, secure_session

logger = logging.getLogger(__name__)


@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """🔐 Monarch Money - Authentication Options

Option 1: Google OAuth (Recommended for local/stdio mode)
   Call the 'authenticate_with_google' tool to open a browser
   and sign in with your Google account.

Option 2: Email/Password (Terminal)
   Run in terminal: python login_setup.py

Option 3: Admin Re-auth (Remote/HTTP mode)
   Visit /admin/reauth on the server to re-authenticate.

✅ Session persists across restarts
✅ Token stored securely in system keyring (local) or server memory (remote)"""


def _authenticate_with_google_impl() -> str:
    """
    Open a browser window to authenticate with Monarch Money using Google OAuth.

    This will:
    1. Open a browser window
    2. Navigate to Monarch login page
    3. You sign in with Google (or email/password)
    4. Token is automatically captured and saved

    Use this when you get authentication errors or need to refresh your session.
    Only available in stdio (local) mode.

    Returns:
        Success or failure message.
    """
    try:
        import asyncio
        from playwright.async_api import async_playwright

        async def _authenticate():
            captured_token = None

            async with async_playwright() as p:
                # Launch browser in non-headless mode
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )

                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                )

                page = await context.new_page()

                # Capture auth token from requests
                async def handle_request(request):
                    nonlocal captured_token
                    auth_header = request.headers.get("authorization", "")
                    if auth_header.startswith("Token ") and not captured_token:
                        captured_token = auth_header.replace("Token ", "")

                page.on("request", handle_request)

                # Navigate to login
                await page.goto("https://app.monarch.com/login")

                # Wait for token capture (max 5 minutes)
                max_wait = 300
                waited = 0
                while not captured_token and waited < max_wait:
                    await asyncio.sleep(1)
                    waited += 1

                await browser.close()

                if captured_token:
                    # Save to keyring
                    secure_session.save_token(captured_token)
                    return {
                        "success": True,
                        "message": "Authentication successful! Token saved.",
                    }
                else:
                    return {
                        "success": False,
                        "message": "Timeout - no token captured. Please try again.",
                    }

        result = run_async(_authenticate())
        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return json.dumps(
            {"success": False, "message": f"Authentication failed: {str(e)}"}, indent=2
        )


def register_stdio_tools():
    """Register tools that are only available in stdio (local) mode."""
    # Set the function name so the MCP tool is registered as 'authenticate_with_google'
    _authenticate_with_google_impl.__name__ = "authenticate_with_google"
    mcp.tool()(_authenticate_with_google_impl)
    logger.info("Registered stdio-only tools: authenticate_with_google")


@mcp.tool()
def check_auth_status() -> str:
    """Check authentication status with Monarch Money.

    Shows token availability, storage tier (in-memory, env var, keyring),
    and environment configuration.
    """
    try:
        token = secure_session.load_token()
        token_status = secure_session.get_token_status()

        if token:
            lines = [f"Authentication token found (length: {len(token)})"]
            if token_status.get("has_in_memory_token"):
                lines.append("  Source: in-memory override")
            elif token_status.get("has_env_var_token"):
                lines.append("  Source: MONARCH_TOKEN environment variable")
            elif token_status.get("has_keyring_token"):
                lines.append("  Source: system keyring")
        else:
            lines = ["No authentication token found"]
            lines.append("Run login_setup.py or visit /admin/reauth to authenticate.")

        email = os.getenv("MONARCH_EMAIL")
        if email:
            lines.append(f"Environment email: {email}")

        lines.append("Tip: Try get_accounts to verify the connection is working.")

        return "\n".join(lines)
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        return f"Auth status check failed:\nError: {str(e)}\nType: {type(e)}\nTraceback:\n{error_details}"
