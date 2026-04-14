"""Monarch Money MCP Server - Core orchestrator.

This module provides the shared infrastructure used by all tool modules:
- mcp: The FastMCP server instance
- run_async(): Thread-pool helper for running async code from sync tool functions
- get_monarch_client(): Authenticated MonarchMoney client factory
- secure_session: Token storage interface
- main(): Entry point (stdio or streamable-http mode)

Tool definitions live in monarch_mcp_server.tools.* and are auto-registered
via @mcp.tool() decorators when imported at the bottom of this file.
"""

import argparse
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from monarchmoney import MonarchMoney, MonarchMoneyEndpoints

from monarch_mcp_server.secure_session import secure_session

# Patch MonarchMoney to use new API domain (monarch.com instead of monarchmoney.com)
MonarchMoneyEndpoints.BASE_URL = "https://api.monarch.com"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")


def run_async(coro):
    """Run async function in a new thread with its own event loop."""

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with ThreadPoolExecutor() as executor:
        future = executor.submit(_run)
        return future.result()


async def get_monarch_client() -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage."""
    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("Using authenticated client from secure keyring storage")
        return client

    # If no secure session, try environment credentials
    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")

    if email and password:
        try:
            client = MonarchMoney()
            await client.login(email, password)
            logger.info(
                "Successfully logged into Monarch Money with environment credentials"
            )

            # Save the session securely
            secure_session.save_authenticated_session(client)

            return client
        except Exception as e:
            logger.error(f"Failed to login to Monarch Money: {e}")
            raise

    raise RuntimeError("Authentication needed! Run: python login_setup.py")


# ---------------------------------------------------------------------------
# Import tool modules to register @mcp.tool() decorators
# ---------------------------------------------------------------------------
import monarch_mcp_server.tools.auth  # noqa: E402, F401
import monarch_mcp_server.tools.accounts  # noqa: E402, F401
import monarch_mcp_server.tools.transactions  # noqa: E402, F401
import monarch_mcp_server.tools.recurring  # noqa: E402, F401
import monarch_mcp_server.tools.categories  # noqa: E402, F401
import monarch_mcp_server.tools.tags  # noqa: E402, F401
import monarch_mcp_server.tools.rules  # noqa: E402, F401
import monarch_mcp_server.tools.budgets  # noqa: E402, F401


def main():
    """Main entry point for the server."""
    parser = argparse.ArgumentParser(description="Monarch Money MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mode: 'stdio' for local (Claude Desktop), 'streamable-http' for remote deployment (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to in HTTP mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="Port to bind to in HTTP mode (default: PORT env var or 8000)",
    )
    args = parser.parse_args()

    transport = args.transport

    if transport == "stdio":
        # Local mode: register browser-based auth tools
        from monarch_mcp_server.tools.auth import register_stdio_tools

        register_stdio_tools()
        logger.info("Starting Monarch Money MCP Server (stdio mode)...")
        mcp.run(transport=transport)
    else:
        # Remote mode: configure HTTP settings, OAuth, and security middleware
        from monarch_mcp_server.remote import _configure_remote_auth, _run_remote_server

        mcp.settings.host = args.host
        mcp.settings.port = args.port
        _configure_remote_auth(mcp)
        logger.info(
            f"Starting Monarch Money MCP Server (streamable-http mode on {args.host}:{args.port})..."
        )
        _run_remote_server(mcp)


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
