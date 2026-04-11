# Monarch MCP Server - Claude Development Guide

## IMPORTANT: Read the Remote MCP Plan

If you are an AI agent working on this codebase, **read `REMOTE_MCP_PLAN.md` first**.
It contains the complete implementation plan for converting this server from local stdio
to a remote Streamable HTTP server with OAuth 2.1 auth, deployable to Railway.

All design decisions, security considerations, file changes, and phased implementation
steps are documented there. Do not make architectural decisions that contradict the plan
without discussing with the user first.

## Project Overview
This is a Model Context Protocol (MCP) server for Monarch Money personal finance platform. We're extending the original robcerda/monarch-mcp-server with enhanced transaction review workflow capabilities. The next major milestone is converting to a remote MCP server -- see `REMOTE_MCP_PLAN.md` for details.

## Goal
Build tools for:
1. Reviewing new transactions (needs_review, recent, uncategorized, no notes filters)
2. Categorizing transactions (with category listing)
3. Labeling transactions (tag support)
4. Adding memos with receipt links
5. Auto-categorization rules (requires API reverse engineering - LAST)
6. Bulk operations

## Architecture
- **Language:** Python 3.12+
- **Framework:** FastMCP from mcp library
- **API:** monarchmoney unofficial library (GraphQL-based)
- **Auth:** Keyring for secure token storage

## Key Files
- `src/monarch_mcp_server/server.py` - Main MCP server with tool definitions
- `src/monarch_mcp_server/secure_session.py` - Keyring-based auth management
- `login_setup.py` - Interactive authentication script
- `tests/` - Test files (pytest + pytest-asyncio)

## Development Patterns

### Adding a New Tool
```python
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

### Monarch API Methods Available
From monarchmoney library:
- `get_transactions(limit, offset, start_date, end_date, search, category_ids, account_ids, tag_ids, has_attachments, has_notes, hidden_from_reports, is_split, is_recurring)`
- `get_transaction_details(transaction_id)`
- `update_transaction(transaction_id, category_id, merchant_name, notes, needs_review, hide_from_reports, amount, date, goal_id)`
- `delete_transaction(transaction_id)`
- `get_transaction_categories()`
- `get_transaction_category_groups()`
- `get_transaction_tags()`
- `create_transaction_tag(name, color)`
- `set_transaction_tags(transaction_id, tag_ids)`
- `update_transaction_splits(transaction_id, split_data)`

## Current Implementation Status
See STATUS.md for detailed progress tracking.

## Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_transactions.py

# Run with coverage
pytest --cov=monarch_mcp_server
```

## Code Style
- Follow existing repo conventions (black, isort)
- Match error handling patterns for open source contribution
- Keep detailed responses (full field output)

## Important Notes
- Rules API is NOT in monarchmoney library - requires reverse engineering (do LAST)
- needs_review filter exists in transaction data but not directly as a filter param
- Keep changes small and incremental for easy PR review
- Always include tests for new functionality

## Contribution Goal
Changes should be suitable for upstream PR to robcerda/monarch-mcp-server.
