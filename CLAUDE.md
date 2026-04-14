# Monarch MCP Server - Agent Development Guide

## Last Updated: 2026-04-13

## IMPORTANT: Read These Documents First

If you are an AI agent working on this codebase:

1. **Read `REFACTOR_PLAN.md`** -- Contains the current work plan (codebase cleanup + feature fixes).
   Check the status checkboxes to see what's done and what's next.
2. **Read `REMOTE_MCP_PLAN.md`** -- Contains the architecture for the remote Streamable HTTP
   deployment (all 7 phases complete). Reference material for OAuth, admin, security design.
3. **Read `STATUS.md`** -- Overall project status, tool inventory, test counts, commit history.

Do not make architectural decisions that contradict these plans without discussing with the user first.

## Project Overview

This is a Model Context Protocol (MCP) server for Monarch Money personal finance platform.
It extends the original robcerda/monarch-mcp-server with:

- Enhanced transaction review workflow (categorization, tagging, notes, bulk ops)
- Account management (create, update, delete accounts with payment fields)
- Recurring transaction management (view, update, disable via merchant entities)
- Transaction auto-categorization rules (reverse-engineered GraphQL API)
- Payment due date visibility (from recurring transaction streams)
- Remote deployment via Streamable HTTP + OAuth 2.1 on Railway
- Admin re-auth web interface for Monarch token management

**Deployment:** Railway (project "elegant-stillness"), auto-deploys from `origin main`.
**URL:** `https://monarch-mcp-server-production-b74d.up.railway.app`
**Claude.ai:** Connected as custom connector on Claude Pro.

## Architecture

- **Language:** Python 3.12+
- **Framework:** FastMCP from mcp library
- **API:** monarchmoney unofficial library (GraphQL-based) + custom GraphQL queries
- **Auth (inbound):** OAuth 2.1 with pre-shared client credentials, password consent gate
- **Auth (outbound):** Monarch Money token (env var on Railway, keyring locally)
- **Transport:** Dual mode -- `stdio` (local/Claude Desktop) or `streamable-http` (remote/Railway)

## Key Files

### Source modules
```
src/monarch_mcp_server/
  server.py            (~130 lines: FastMCP init, run_async, get_monarch_client, main)
  queries.py           (all GraphQL query/mutation constants)
  remote.py            (_configure_remote_auth, _run_remote_server)
  tools/
    __init__.py        (package marker)
    auth.py            (setup_authentication, check_auth_status, register_stdio_tools)
    accounts.py        (get_accounts, create/update/delete_account, refresh_accounts)
    transactions.py    (get/update/create/delete_transaction, search, bulk ops, review)
    recurring.py       (get_recurring_transactions, merchant details, update/disable recurring)
    categories.py      (get_categories, get_category_groups)
    tags.py            (get_tags, set_transaction_tags, create_tag)
    rules.py           (transaction rule CRUD)
    budgets.py         (get_budgets, get_cashflow, get_account_holdings)
  admin.py             (admin re-auth pages, password-protected)
  oauth.py             (OAuth 2.1 provider, pre-shared credentials, in-memory tokens)
  security.py          (rate limiting, Origin validation middleware)
  secure_session.py    (token storage: in-memory > env var > keyring)
```

### Tests
- `tests/conftest.py` -- Shared mock setup for monarchmoney module
- `tests/test_*.py` -- 8 test files, 147+ tests
- Test `@patch` paths use `monarch_mcp_server.tools.MODULE.get_monarch_client`

## Development Patterns

### Adding a New Tool (post-refactor)

Create the tool in the appropriate `tools/*.py` file:

```python
import json
import logging
from typing import Optional

from monarch_mcp_server.server import mcp, run_async, get_monarch_client

logger = logging.getLogger(__name__)

@mcp.tool()
def tool_name(param: str, optional_param: Optional[str] = None) -> str:
    """Tool description for MCP."""
    try:
        async def _async_impl():
            client = await get_monarch_client()
            return await client.some_method()

        result = run_async(_async_impl())
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed: {e}")
        return f"Error: {str(e)}"
```

The tool is auto-registered when `server.py` imports the tool module.

### Custom GraphQL Queries

When the monarchmoney library doesn't support a needed field or operation:

1. Add the GraphQL query/mutation constant to `queries.py`
2. Use `client.gql_call()` with `gql()` from the `gql` library
3. Always implement a fallback to the library method when possible

```python
from gql import gql
from monarch_mcp_server.queries import MY_CUSTOM_QUERY

query = gql(MY_CUSTOM_QUERY)
result = await client.gql_call(
    operation="OperationName",
    graphql_query=query,
    variables={"key": "value"},
)
```

### Test Patterns

- All test files use shared mocks from `tests/conftest.py`
- Mock the monarchmoney client via `@patch("monarch_mcp_server.tools.MODULE.get_monarch_client")`
- Use `AsyncMock()` for the client since all Monarch API methods are async
- Always test: success path, error handling, edge cases (None values, empty results)

```python
from unittest.mock import AsyncMock, patch

class TestMyTool:
    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_success(self, mock_get_client):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client
        mock_client.some_method.return_value = {"data": "value"}

        from monarch_mcp_server.tools.accounts import my_tool
        result = my_tool(param="value")
        # assertions...
```

## Monarch API Reference

### Library Methods (monarchmoney package)
- `get_transactions(limit, offset, start_date, end_date, search, category_ids, account_ids, tag_ids, has_attachments, has_notes, hidden_from_reports, is_split, is_recurring)`
- `get_transaction_details(transaction_id)`
- `update_transaction(transaction_id, category_id, merchant_name, notes, needs_review, hide_from_reports, amount, date, goal_id)`
- `delete_transaction(transaction_id)`
- `get_transaction_categories()`, `get_transaction_category_groups()`
- `get_transaction_tags()`, `create_transaction_tag(name, color)`, `set_transaction_tags(transaction_id, tag_ids)`
- `get_accounts()`, `create_manual_account()`, `update_account()`, `delete_account()`
- `get_recurring_transactions(start_date, end_date)`
- `get_budgets()`, `get_cashflow()`, `get_account_holdings()`
- `request_accounts_refresh()`

### Custom GraphQL (beyond library)
- **Account payment fields:** `minimumPayment`, `apr`, `interestRate`, `limit` (via custom account query)
- **Account payment writes:** Same fields writable via `UpdateAccountMutationInput`
- **Recurring management:** `Common_GetEditMerchant`, `Common_UpdateMerchant` (with `recurrence` input)
- **Transaction rules:** `GetTransactionRules`, `CreateTransactionRuleV2`, `UpdateTransactionRuleV2`, `DeleteTransactionRule`
- **Recurring streams:** `recurringTransactionStreams` query (all streams, no date window)
- **Enriched recurring items:** Extended `Web_GetUpcomingRecurringTransactionItems` with `baseDate`, `reviewStatus`, `recurringType`, `isLate`, `isCompleted`, `markedPaidAt`

### API Quirks
- Domain: `api.monarch.com` (migrated from `api.monarchmoney.com`, patched in server.py)
- GraphQL introspection disabled for non-admin users
- Browser-like headers required for raw aiohttp calls (Cloudflare)
- Railway datacenter IPs trigger Monarch bot detection on login (use MONARCH_TOKEN env var)
- `dayOfTheMonth` field exists on RecurringTransactionStream but is always null; use `baseDate` instead

## Testing
```bash
# Run all tests
.venv/bin/python -m pytest

# Run specific test file
.venv/bin/python -m pytest tests/test_accounts.py

# Run with verbose output
.venv/bin/python -m pytest -v

# Run with coverage
.venv/bin/python -m pytest --cov=monarch_mcp_server
```

## Code Style
- Follow existing repo conventions (black, isort)
- Double quotes for strings (enforced by black)
- Match error handling patterns for open source contribution
- Keep detailed responses (full field output in JSON)
- Always include tests for new functionality

## Environment Variables

| Variable | Required | Mode | Description |
|---|---|---|---|
| `MCP_AUTH_PASSWORD` | Yes (remote) | Remote | Password for OAuth consent gate + admin pages |
| `MCP_CLIENT_ID` | Yes (remote) | Remote | Pre-shared OAuth client ID |
| `MCP_CLIENT_SECRET` | Yes (remote) | Remote | Pre-shared OAuth client secret |
| `MONARCH_TOKEN` | Yes (remote) | Remote | Monarch Money API token |
| `MCP_SERVER_URL` | Yes (remote) | Remote | Public URL (for OAuth metadata) |
| `MONARCH_EMAIL` | No | Local | Fallback for Monarch auth |
| `MONARCH_PASSWORD` | No | Local | Fallback for Monarch auth |
