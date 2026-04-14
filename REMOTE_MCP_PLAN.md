# Remote MCP Server Implementation Plan

## Status: ALL 7 PHASES COMPLETE

Deployed to Railway at `https://monarch-mcp-server-production-b74d.up.railway.app`.
Connected to Claude.ai as custom connector. All environment variables configured.
This document is retained as **architectural reference** for the OAuth, admin,
security, and deployment design.

## Last Updated: 2026-04-13

## Overview

Convert the Monarch MCP Server from a local stdio-based server (Claude Desktop) to a
remote Streamable HTTP server deployable to Railway, accessible as a custom connector
on claude.ai. This enables using Monarch Money tools from any Claude interface (web,
mobile, Cowork, Desktop) without running anything locally.

## Architecture

```
+-------------------+     HTTPS        +----------------------------+     HTTPS     +-------------------+
|  claude.ai        | ---------------> |  Monarch MCP Server        | ------------> |  Monarch Money    |
|  (Anthropic       |  Bearer Token    |  (Railway)                 |  Token auth   |  API              |
|   cloud)          |  (OAuth 2.1)     |                            |               |                   |
+-------------------+                  |  - Streamable HTTP /mcp    |               +-------------------+
                                       |  - Built-in OAuth AS       |
                                       |  - Admin re-auth page      |
                                       +----------------------------+
```

### Two Auth Layers

| Layer | Purpose | Mechanism |
|-------|---------|-----------|
| **Inbound** (Claude -> MCP server) | Ensure only you can call MCP tools | Built-in OAuth 2.1 AS with password gate, pre-shared client credentials, no DCR |
| **Outbound** (MCP server -> Monarch Money) | Authenticate with Monarch's API | Token stored as Railway secret / in-memory, refreshed via admin web form |

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inbound auth | Built-in OAuth AS (MCP SDK) | Self-contained, no external auth provider dependency |
| Dynamic Client Registration | **Disabled** | Prevents unknown clients from registering. Pre-shared client_id/secret entered in Claude.ai Advanced Settings |
| OAuth consent UI | Simple HTML password gate | Single-user server; `MCP_AUTH_PASSWORD` env var |
| Monarch re-auth | Web form at `/admin/reauth` (email/password + MFA) | Reuses `MonarchMoney.login()` logic from `login_setup.py`. Works headlessly on Railway |
| Transport | Dual mode: stdio (local) + streamable-http (remote) | `--transport` CLI flag, default `stdio` for backwards compatibility |
| Deployment | Railway | Auto HTTPS, secrets management, Dockerfile deploys |
| Claude plan | Pro | Unlimited custom connectors |

## Security Design

### Three layers of protection for inbound access:

1. **Pre-shared client credentials** -- Only the client_id/secret you configure in Claude.ai can initiate OAuth. No DCR endpoint exists.
2. **Password consent gate** -- Even with valid client credentials, an access token is only issued after entering `MCP_AUTH_PASSWORD` on the consent page.
3. **Anthropic IP allowlisting** (optional defense-in-depth) -- Restrict inbound connections to Anthropic's published IP ranges.

### Additional hardening:
- HTTPS enforced (Railway TLS termination)
- OAuth 2.1 with PKCE on all auth flows
- Short-lived access tokens (1 hour) with refresh token support (30 days)
- Refresh token rotation
- Validate `Origin` header to prevent DNS rebinding
- No sensitive data in error responses
- Rate limiting on auth endpoints
- `authenticate_with_google` MCP tool disabled in remote mode

### Monarch token security:
- Token stored as Railway encrypted secret (`MONARCH_TOKEN` env var)
- In-memory override when refreshed via admin page
- Email/password only in memory during the API call, never persisted
- Admin re-auth page protected by `MCP_AUTH_PASSWORD`

## MCP Python SDK Usage

We use the SDK's built-in OAuth 2.1 framework (mcp v1.13.1). The SDK provides:

| SDK Component | What It Does |
|---|---|
| `OAuthAuthorizationServerProvider` protocol | Interface we implement for auth logic + storage |
| `AuthSettings` model | Config: issuer URL, resource server URL, scopes, DCR options |
| `create_auth_routes()` | Auto-generates `/authorize`, `/token`, `/.well-known/oauth-authorization-server`, `/revoke` |
| `BearerAuthBackend` middleware | Extracts + validates Bearer tokens on every request |
| `RequireAuthMiddleware` | Returns 401/403 for unauthenticated/unauthorized requests |
| `ProviderTokenVerifier` | Auto-wraps our provider's `load_access_token()` into token validation |

**We implement:** `OAuthAuthorizationServerProvider` (storage + password gate logic).
**The SDK handles:** HTTP routing, middleware, PKCE enforcement, token transport, metadata endpoints, WWW-Authenticate headers.

## Implementation Phases

### Phase 1: Transport + Dual Mode

**Files:** `server.py`, `pyproject.toml`

- Modify `main()` to accept `--transport` CLI arg (`stdio` | `streamable-http`, default: `stdio`)
- Add `host="0.0.0.0"`, `port=8000`, `streamable_http_path="/mcp"` to FastMCP init when remote
- Conditionally register `authenticate_with_google` tool only in stdio mode
- Update `pyproject.toml` entry point if needed
- Verify `uvicorn` is available (should be pulled in by `mcp[cli]`)

### Phase 2: Monarch Token Storage (Remote Fallback)

**Files:** `secure_session.py`

- Modify `SecureMonarchSession` to support:
  - In-memory token override (for runtime updates from re-auth flow)
  - `MONARCH_TOKEN` env var fallback when keyring is unavailable
- Token resolution hierarchy: in-memory override > env var > keyring
- Add `update_token_in_memory(token)` method for the admin re-auth flow
- Keep keyring path working for local/stdio mode

### Phase 3: Built-in OAuth Authorization Server

**Files:** `src/monarch_mcp_server/oauth.py` (new), `server.py`

#### `oauth.py` -- Implement `OAuthAuthorizationServerProvider`:

| Method | Implementation |
|---|---|
| `get_client(client_id)` | Look up pre-shared credentials from `MCP_CLIENT_ID` / `MCP_CLIENT_SECRET` env vars. Return `None` for unknown clients. |
| `register_client(client_info)` | Raise error -- DCR disabled |
| `authorize(client, params)` | Render HTML password form. Validate against `MCP_AUTH_PASSWORD`. Generate + store auth code. Return redirect URL with code. |
| `load_authorization_code(...)` | Retrieve stored auth code |
| `exchange_authorization_code(...)` | Validate code + PKCE, generate access token (1hr) + refresh token (30d), return `OAuthToken` |
| `load_refresh_token(...)` | Retrieve stored refresh token |
| `exchange_refresh_token(...)` | Validate refresh token, rotate it, issue new access token |
| `load_access_token(token)` | Validate access token (called by SDK middleware on every request) |
| `revoke_token(token)` | Remove token from store |

#### Storage:
- In-memory dicts for auth codes, access tokens, refresh tokens
- Single-user server -- no database needed
- Tokens survive until server restarts (Railway redeploys)
- Claude.ai handles re-auth via refresh tokens transparently

#### Wire into FastMCP in `server.py`:

```python
from monarch_mcp_server.oauth import MonarchOAuthProvider
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

provider = MonarchOAuthProvider()

mcp = FastMCP(
    "Monarch Money MCP Server",
    host="0.0.0.0",
    port=8000,
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://<railway-url>"),
        resource_server_url=AnyHttpUrl("https://<railway-url>"),
        client_registration_options=ClientRegistrationOptions(enabled=False),
        revocation_options=RevocationOptions(enabled=True),
    ),
)
```

Auth config only applied when `--transport=streamable-http`.

### Phase 4: Monarch Re-auth Admin Page

**Files:** `src/monarch_mcp_server/admin.py` (new), `server.py`

- Create password-protected `/admin/reauth` Starlette route
- **Step 1:** Enter `MCP_AUTH_PASSWORD`
- **Step 2:** Enter Monarch email + password
- **Step 3:** If MFA required, show MFA code field
- Calls `MonarchMoney.login()` / `multi_factor_authenticate()` (logic reused from `login_setup.py`)
- Stores new token via `secure_session.update_token_in_memory(token)`
- Shows auth status page (token exists, last refreshed timestamp)
- Mount as additional Starlette routes alongside MCP app

### Phase 5: Deployment (Railway)

**Files:** `Dockerfile` (new), `railway.toml` or `railway.json` (new, if needed)

#### Dockerfile:
- Base: `python:3.12-slim`
- Install `uv`
- Copy `pyproject.toml`, `uv.lock`, `src/`
- `uv sync --frozen`
- Expose port 8000
- CMD: `uv run monarch-mcp-server --transport streamable-http`

#### Railway secrets:

| Secret | Purpose |
|---|---|
| `MCP_AUTH_PASSWORD` | Password for OAuth consent gate + admin pages |
| `MCP_CLIENT_ID` | Pre-shared OAuth client ID (generate a UUID) |
| `MCP_CLIENT_SECRET` | Pre-shared OAuth client secret (generate a strong random string) |
| `MONARCH_TOKEN` | Initial Monarch Money auth token (from local `login_setup.py`) |
| `MCP_SERVER_URL` | Public URL of the server (for OAuth metadata) |

#### Railway provides:
- Automatic HTTPS/TLS on `*.up.railway.app`
- Health checks
- Zero-downtime deploys
- Encrypted secrets at rest

### Phase 6: Security Hardening

- Validate `Origin` header on all incoming connections
- Rate limit `/authorize` and `/token` endpoints
- Rate limit `/admin/reauth`
- Ensure no sensitive data in error responses
- Optional: IP allowlist for Anthropic's published ranges
- Disable `authenticate_with_google` tool in remote mode
- Add logging for auth events (successful logins, failed attempts, token refreshes)

### Phase 7: Connect to Claude.ai

1. Deploy to Railway, get URL (e.g., `https://monarch-mcp-server.up.railway.app`)
2. Go to claude.ai > Customize > Connectors > "+" > Add custom connector
3. URL: `https://monarch-mcp-server.up.railway.app/mcp`
4. Advanced Settings: enter `MCP_CLIENT_ID` and `MCP_CLIENT_SECRET` values
5. Claude initiates OAuth > redirects to password gate > enter `MCP_AUTH_PASSWORD` > approve
6. Enable connector in conversations via "+" > Connectors toggle

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/monarch_mcp_server/server.py` | Modify | `--transport` flag, auth config, conditional tool registration |
| `src/monarch_mcp_server/secure_session.py` | Modify | Env var fallback, in-memory token storage |
| `src/monarch_mcp_server/oauth.py` | **Create** | OAuth AS provider implementation, password consent page, token store |
| `src/monarch_mcp_server/admin.py` | **Create** | Monarch re-auth web form (email/password + MFA) |
| `Dockerfile` | **Create** | Container build for Railway |
| `pyproject.toml` | Modify | Add any new deps if needed |
| `tests/test_oauth.py` | **Create** | OAuth flow tests |
| `tests/test_admin.py` | **Create** | Re-auth flow tests |
| `CLAUDE.md` | Modify | Reference this plan document |
| `REMOTE_MCP_PLAN.md` | **Create** | This document |

## Existing Code Reuse

| Existing Code | Reused? | Notes |
|---|---|---|
| `login_setup.py` auth logic | **Yes** | `MonarchMoney.login()` + `multi_factor_authenticate()` reused in admin.py web form |
| `google_login.py` | **No (remote)** | Requires visible browser. Kept for local/stdio mode only. |
| `authenticate_with_google` MCP tool | **No (remote)** | Same Playwright dependency. Registered only in stdio mode. |
| `secure_session.py` keyring logic | **Yes** | Extended with env var + in-memory fallbacks |
| All existing MCP tools | **Yes** | All 25+ tools work unchanged -- only transport + auth wrapper changes |
| All existing tests | **Yes** | Should continue passing -- tool logic is untouched |

## Environment Variables (Remote Mode)

| Variable | Required | Description |
|---|---|---|
| `MCP_AUTH_PASSWORD` | Yes | Password for OAuth consent gate and admin pages |
| `MCP_CLIENT_ID` | Yes | Pre-shared OAuth client ID |
| `MCP_CLIENT_SECRET` | Yes | Pre-shared OAuth client secret |
| `MONARCH_TOKEN` | Yes (initial) | Monarch Money API token. Can be refreshed via admin page at runtime. |
| `MCP_SERVER_URL` | Yes | Public URL of the server (for OAuth metadata, e.g., `https://monarch-mcp-server.up.railway.app`) |
| `MONARCH_EMAIL` | No | Fallback for Monarch auth (existing behavior) |
| `MONARCH_PASSWORD` | No | Fallback for Monarch auth (existing behavior) |
