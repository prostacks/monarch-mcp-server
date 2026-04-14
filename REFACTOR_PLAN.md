# Codebase Refactor & Feature Fix Plan

## Last Updated: 2026-04-13

## Overview

After multiple rounds of feature additions (remote deployment, Issues #1/#2, payment fields,
recurring management, due date visibility), the codebase needs a cleanup pass before
implementing the final 3 feature fixes. This document covers both the cleanup (Phase A)
and the feature fixes (Phase B).

## Status Key
- [ ] Not started
- [~] In progress
- [x] Complete

---

## Phase A: Codebase Cleanup (7 steps)

### A1: Create `tests/conftest.py` with shared mock setup [x]

**Problem:** All 8 test files independently mock `sys.modules["monarchmoney"]` with
5-8 lines of boilerplate. Two incompatible variants exist:
- **Safe variant** (test_accounts, test_account_management, test_recurring_management, test_admin):
  Uses `type("RequireMFAException", (Exception,), {})` -- creates a proper subclass.
- **Dangerous variant** (test_transactions, test_categories, test_rules, test_tags):
  Uses `RequireMFAException = Exception` -- makes `except RequireMFAException` catch ALL exceptions.

**Changes:**
1. Create `tests/conftest.py` with module-level `sys.modules` mock using the safe variant
2. Include `MonarchMoneyEndpoints` mock (currently missing from 5 files)
3. Remove duplicated mock blocks from all 8 test files
4. Remove unused `import pytest` from 7 files (keep in test_admin.py which uses `@pytest.mark.asyncio`)

**Files modified:** `tests/conftest.py` (new), all 8 `tests/test_*.py` files

**Verification:** `pytest` -- 147 tests passing

---

### A2: Remove `asyncio` dependency from pyproject.toml [x]

**Problem:** `asyncio>=3.4.3` is a Python 3.3 backport from PyPI. On Python 3.12+,
asyncio is part of stdlib. Installing the PyPI package is unnecessary and potentially risky.

Also move `playwright>=1.40.0` from core dependencies to optional `[project.optional-dependencies]`
since it's only needed for local stdio browser-based auth, not for the Railway deployment.

**Changes:**
1. Remove `asyncio>=3.4.3` from `[project.dependencies]`
2. Move `playwright>=1.40.0` from `[project.dependencies]` to a new `[project.optional-dependencies] local` group

**Files modified:** `pyproject.toml`

**Verification:** `uv sync` succeeds, `pytest` passes

---

### A3: Fix Dockerfile EXPOSE [x]

**Problem:** `EXPOSE ${PORT}` doesn't expand variables in Docker. It's a no-op.

**Changes:**
1. Change `EXPOSE ${PORT}` to `EXPOSE 8000`

**Files modified:** `Dockerfile`

**Verification:** Visual inspection (no runtime test needed)

---

### A4: Remove dead code from server.py [x]

**Problem:** Several unused items accumulated over development:
- `import threading` (line 10) -- unused
- `from typing import ... Union` (line 7) -- unused
- `MonarchConfig` class (lines 51-58) -- defined but never used
- `_authenticate_with_google_impl` re-imports `asyncio` (line 129) -- already at module level
- `check_auth_status` and `debug_session_loading` are near-duplicates

**Changes:**
1. Remove `import threading`
2. Remove `Union` from typing imports
3. Remove `MonarchConfig` class
4. Remove redundant `import asyncio` inside `_authenticate_with_google_impl`
5. Merge `check_auth_status` and `debug_session_loading` into a single `check_auth_status` tool

**Files modified:** `src/monarch_mcp_server/server.py`

**Verification:** `pytest` passes

---

### A5: Combine dual `run_async` calls in `get_accounts` [x]

**Problem:** `get_accounts()` makes two separate `run_async()` calls (lines 422 and 483),
each spinning up a new thread + event loop. These should be a single async function.

**Changes:**
1. Merge `_get_accounts()` and `_get_due_days()` into a single async function called once via `run_async()`
2. The combined function fetches accounts, identifies credit/loan accounts, fetches recurring
   transactions, and returns the complete enriched list

**Files modified:** `src/monarch_mcp_server/server.py` (tools/accounts.py after split)

**Verification:** `pytest tests/test_accounts.py` -- all 19 tests pass

---

### A6: Extract duplicate HTML from server.py to admin.py templates [x]

**Problem:** `server.py` contains `LOGIN_PAGE_HTML` (~110 lines of inline HTML/CSS) that
largely duplicates `admin.py`'s `_BASE_STYLES` and `_render_page()`. Both define the same
dark theme, input styles, button styles, etc.

**Changes:**
1. Refactor `LOGIN_PAGE_HTML` to use `admin.py`'s `_render_page()` helper
2. Add any login-specific styles (`.warning` class) to `_BASE_STYLES`
3. Keep the form-specific HTML as a template string, but eliminate the duplicated CSS

**Files modified:** `src/monarch_mcp_server/admin.py`, `src/monarch_mcp_server/server.py`
(later: `src/monarch_mcp_server/remote.py`)

**Verification:** Manual test of `/auth/login` page rendering (or visual inspection)

---

### A7: Split server.py into modular files [x]

**Problem:** `server.py` is 3,043 lines containing GraphQL constants, all tool definitions,
OAuth setup, HTTP server bootstrap, and the login page HTML. This is unwieldy.

**New module structure:**

```
src/monarch_mcp_server/
  __init__.py              (unchanged)
  server.py                (~150 lines: FastMCP init, run_async, get_monarch_client, main, imports)
  queries.py               (~300 lines: all GraphQL query/mutation constants)
  remote.py                (~200 lines: _configure_remote_auth, _run_remote_server, LOGIN_PAGE_HTML)
  tools/
    __init__.py            (empty package marker)
    auth.py                (setup_authentication, check_auth_status, register_stdio_tools)
    accounts.py            (get_accounts, create_account, update_account, delete_account, refresh_accounts)
    transactions.py        (get_transactions, update_transaction, create_transaction, delete_transaction,
                            search_transactions, get_transaction_details, set_transaction_category,
                            update_transaction_notes, mark_transaction_reviewed,
                            bulk_categorize_transactions, get_transactions_needing_review)
    recurring.py           (get_recurring_transactions, get_merchant_details,
                            update_recurring_transaction, disable_recurring_transaction)
    categories.py          (get_categories, get_category_groups)
    tags.py                (get_tags, set_transaction_tags, create_tag)
    rules.py               (get_transaction_rules, create_transaction_rule,
                            update_transaction_rule, delete_transaction_rule)
    budgets.py             (get_budgets, get_cashflow, get_account_holdings)
  admin.py                 (unchanged)
  oauth.py                 (unchanged)
  security.py              (unchanged)
  secure_session.py        (unchanged)
```

**Import pattern for tool files:**
```python
# Each tool file imports these from the core server module:
from monarch_mcp_server.server import mcp, run_async, get_monarch_client, logger
```

**server.py imports all tool modules to trigger @mcp.tool() registration:**
```python
# Import tool modules to register @mcp.tool() decorators
import monarch_mcp_server.tools.auth
import monarch_mcp_server.tools.accounts
import monarch_mcp_server.tools.transactions
import monarch_mcp_server.tools.recurring
import monarch_mcp_server.tools.categories
import monarch_mcp_server.tools.tags
import monarch_mcp_server.tools.rules
import monarch_mcp_server.tools.budgets
```

**Test file import changes:** Test `@patch` paths change from
`monarch_mcp_server.server.get_monarch_client` to the tool-specific module, e.g.:
`monarch_mcp_server.tools.accounts.get_monarch_client`

**Changes:**
1. Create `src/monarch_mcp_server/queries.py` with all GraphQL constants
2. Create `src/monarch_mcp_server/remote.py` with remote server setup
3. Create `src/monarch_mcp_server/tools/` package with 8 tool files
4. Rewrite `server.py` as slim orchestrator (~150 lines)
5. Update all test file `@patch` paths
6. Update `pyproject.toml` entry point if needed (should still be `server:main`)

**Files created:** `queries.py`, `remote.py`, `tools/__init__.py`, `tools/auth.py`,
`tools/accounts.py`, `tools/transactions.py`, `tools/recurring.py`, `tools/categories.py`,
`tools/tags.py`, `tools/rules.py`, `tools/budgets.py`

**Files modified:** `server.py` (rewritten), all 8 test files (patch paths)

**Verification:** `pytest` -- 147 tests passing

---

## Phase B: Feature Fixes (3 items)

These fix gaps discovered during a real Claude conversation where the agent struggled
to manage recurring transactions for a credit account.

### B1: Add merchant_id to get_accounts payment_details [x]

**Problem:** When `_get_due_days` finds a recurring stream for a credit/loan account,
the `payment_details` dict only includes `due_day`. The agent has no way to go directly
from an account to the merchant_id needed for `update_recurring_transaction` without
calling `get_recurring_transactions` first.

**Changes:**
1. In `_get_due_days` (tools/accounts.py), also capture `stream.merchant.id` and `stream.id`
2. Return them alongside `due_day` in the due_day_map
3. Surface as `recurring_merchant_id` and `recurring_stream_id` in `payment_details`

**Example output after fix:**
```json
{
  "payment_details": {
    "minimum_payment": 35.0,
    "apr": 25.74,
    "due_day": 15,
    "recurring_merchant_id": "123456",
    "recurring_stream_id": "789012"
  }
}
```

**Files modified:** `tools/accounts.py`, `tests/test_accounts.py`

**Verification:** `pytest tests/test_accounts.py` passes with new assertions

---

### B2: Add `get_recurring_streams` tool [x]

**Problem:** `get_recurring_transactions` queries `recurringTransactionItems(startDate, endDate)`,
which only returns items within a date window. Streams without upcoming items (like the
Lending Club loan) are invisible. The Monarch web app uses `recurringTransactionStreams`
which returns ALL streams regardless of date.

**Changes:**
1. Add new GraphQL query `GET_RECURRING_STREAMS_QUERY` (from HAR entry 67:
   `Common_GetAllRecurringTransactionItems`) to `queries.py`
2. Add `get_recurring_streams` tool to `tools/recurring.py`
3. Returns all streams with: stream details, account association, merchant,
   `nextForecastedTransaction`, and `isActive` status
4. Supports optional filters: `include_liabilities` (default True),
   `include_pending` (default True)

**GraphQL query (from HAR):**
```graphql
query Common_GetAllRecurringTransactionItems(
    $filters: RecurringTransactionFilter,
    $includeLiabilities: Boolean,
    $includePending: Boolean
) {
    recurringTransactionStreams(
        filters: $filters,
        includeLiabilities: $includeLiabilities,
        includePending: $includePending
    ) {
        id
        frequency
        amount
        baseDate
        isActive
        isApproximate
        name
        logoUrl
        reviewStatus
        recurringType
        merchant {
            id
            name
            logoUrl
            __typename
        }
        account {
            id
            displayName
            __typename
        }
        category {
            id
            name
            __typename
        }
        nextForecastedTransaction {
            date
            amount
            __typename
        }
        __typename
    }
}
```

**Files modified:** `queries.py`, `tools/recurring.py`, `tests/test_recurring_management.py`

**Verification:** `pytest tests/test_recurring_management.py` passes with new tests

---

### B3: Enable creating recurring streams on merchants [x]

**Problem:** `update_recurring_transaction` currently fails if a merchant has no existing
recurring stream (returns error message). But we should be able to create one by setting
`isRecurring: true` with the required fields.

Also update `_get_due_days` to use `recurringTransactionStreams` as a fallback when
the item-based query doesn't find a match (fixes the Lending Club gap from the read side too).

**Changes:**
1. In `update_recurring_transaction`, when `stream` is None:
   - If user provided `frequency`, `base_date`, and `amount`: create the stream
     by calling `Common_UpdateMerchant` with `recurrence.isRecurring: true`
   - `is_active` defaults to `true` when creating
   - If required params missing: return helpful error listing what's needed
2. Update `_get_due_days` to use `get_recurring_streams` query as a fallback when
   the item-based query doesn't find a due_day for an account

**Files modified:** `tools/recurring.py`, `tools/accounts.py`, `queries.py` (if needed),
`tests/test_recurring_management.py`, `tests/test_accounts.py`

**Verification:** `pytest` -- all tests pass

---

## Documentation Updates (at each phase)

After completing each phase step (A1-A7, B1-B3):

1. Update this file (`REFACTOR_PLAN.md`): Mark the step `[x]` complete
2. If the step changes file structure: Update `CLAUDE.md` Key Files section
3. If the step changes test counts: Update `STATUS.md` test counts
4. After Phase A is fully complete: Update `CLAUDE.md` architecture + patterns sections
5. After Phase B is fully complete: Update `STATUS.md` with new tools + final test count

---

## Monarch API Discoveries (Reference)

These are facts discovered during development that inform the implementation:

### Payment Fields (on Account type)
- `minimumPayment`: works for credit cards and loans
- `apr`: works for credit cards (None for loans)
- `interestRate`: works for loans (None for credit cards)
- `limit`: credit limit for credit cards (None for loans)
- Fields that do NOT exist: `creditLimit`, `availableCredit`, `paymentDueDate`, `pastDueAmount`

### Recurring Transaction Architecture
- Recurring transactions are managed via the **merchant** entity, not standalone
- `Common_UpdateMerchant` mutation accepts `recurrence` input with:
  `isRecurring`, `frequency`, `baseDate`, `amount`, `isActive`
- `baseDate` on `RecurringTransactionStream` is the authoritative due/billing date
- `dayOfTheMonth` field exists in schema but is always null

### Two Recurring Query Types
- `recurringTransactionItems(startDate, endDate)` -- calendar items in date range
  (used by `get_recurring_transactions`)
- `recurringTransactionStreams(filters, includeLiabilities, includePending)` -- ALL streams
  (will be used by `get_recurring_streams` in B2)

### Stream Fields (validated via live API)
- `baseDate` (ALL OK), `reviewStatus` (values: "automatic_approved"/"approved"),
  `recurringType` ("expense"/"income"), `isLate`, `isCompleted`, `markedPaidAt`

### API Quirks
- Monarch API migrated from `api.monarchmoney.com` to `api.monarch.com`
  (patched in server.py line 22)
- GraphQL introspection disabled for non-admin users
- Browser-like headers required for raw aiohttp calls (Cloudflare)
- Railway datacenter IPs trigger Monarch bot detection on login
  (workaround: MONARCH_TOKEN env var)
