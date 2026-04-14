# Implementation Status

## Last Updated: 2026-04-13

## Current Phase: Codebase Refactor + Feature Fixes

See `REFACTOR_PLAN.md` for the detailed execution plan.

## Summary
- **Total Tools:** ~31 (added get_recurring_streams in B2)
- **Total Tests:** 162 (all passing)
- **Deployment:** Railway (streamable-http), connected to Claude.ai as custom connector

---

## Completed Work

### Original Tool Development (Phases 1-3)
19 tools built in the initial development phase:

| Phase | Tools | Tests |
|-------|-------|-------|
| Phase 1: Core Review | get_categories, get_category_groups, get_transactions_needing_review, set_transaction_category, update_transaction_notes, mark_transaction_reviewed | 6 + 30 |
| Phase 2: Bulk Ops & Tags | bulk_categorize, get_tags, set_transaction_tags, create_tag, search_transactions, get_transaction_details, delete_transaction, get_recurring_transactions | 9 |
| Phase 3: Transaction Rules | get_transaction_rules, create_transaction_rule, update_transaction_rule, delete_transaction_rule | 12 |

### Remote MCP Server Conversion (REMOTE_MCP_PLAN.md Phases 1-7) -- COMPLETE
Converted from local stdio-based server to remote Streamable HTTP server on Railway:

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Transport + Dual Mode (stdio/streamable-http) | Complete |
| Phase 2 | Monarch Token Storage (in-memory > env var > keyring) | Complete |
| Phase 3 | Built-in OAuth 2.1 Authorization Server | Complete |
| Phase 4 | Monarch Re-auth Admin Page (/admin/status, /admin/reauth) | Complete |
| Phase 5 | Deployment (Railway, Dockerfile) | Complete |
| Phase 6 | Security Hardening (rate limiting, Origin validation, logging) | Complete |
| Phase 7 | Connect to Claude.ai as custom connector | Complete |

### Issue #1: Fix & Expand update_transaction (commit 2268dd5) -- COMPLETE
- Fixed description update bug
- Added merchant_name, notes, review_status, hide_from_reports parameters

### Issue #2: Add Account Lifecycle Tools (commit 2268dd5) -- COMPLETE
- create_account: Create manual accounts
- update_account: Update with payment fields (minimumPayment, interestRate, apr)
- delete_account: Delete accounts

### Enriched get_accounts with Payment Fields (commit 1dff744) -- COMPLETE
Custom GraphQL query adds minimumPayment, apr, interestRate, limit fields for credit/loan accounts.

### Payment Due Date Visibility Feature -- READ + WRITE SIDES COMPLETE

**Commit 66de23c:**
- Probed live API for undocumented stream fields
- Enriched get_recurring_transactions with custom GraphQL, account.id, category.id, merchant.id
- Added due_day to get_accounts payment_details from recurring transactions

**Commit 853efeb:**
- Upgraded due_day source from item.date to stream.baseDate (authoritative)
- Added 3 new tools: get_merchant_details, update_recurring_transaction, disable_recurring_transaction
- Enriched recurring query with baseDate, reviewStatus, recurringType, isLate, isCompleted, markedPaidAt
- All fields validated against live API
- 147 tests passing (19 new)

---

## Current Work: Codebase Refactor + Feature Fixes

### Phase A: Cleanup (see REFACTOR_PLAN.md) -- COMPLETE
7 cleanup steps to improve code quality after multiple rounds of feature additions:
- A1 [x]: Create tests/conftest.py with shared mock setup
- A2 [x]: Remove unnecessary asyncio dependency
- A3 [x]: Fix Dockerfile EXPOSE
- A4 [x]: Remove dead code from server.py
- A5 [x]: Combine dual run_async in get_accounts
- A6 [x]: Extract duplicate HTML to admin.py templates
- A7 [x]: Split server.py into modular files (queries.py, remote.py, tools/)

### Phase B: Feature Fixes (see REFACTOR_PLAN.md) -- COMPLETE
3 fixes from gap analysis of a real Claude conversation failure:
- B1 [x]: Add recurring_merchant_id/recurring_stream_id to get_accounts payment_details
- B2 [x]: Add get_recurring_streams tool (stream-level query, fixes Lending Club gap)
- B3 [x]: Enable creating recurring streams on merchants + _fetch_due_days streams fallback

### Issue #3: Fix get_recurring_streams GraphQL error -- COMPLETE
Monarch removed the `recurringTransactionStreams` top-level GraphQL field from their API (confirmed April 2026).
- **Workaround:** Rewrote `get_recurring_streams` to use `recurringTransactionItems` with a wide date range (2020-2030), deduplicating by stream ID to reconstruct a stream-level view.
- **Also fixed:** `_fetch_due_days` Phase 2 fallback in `get_accounts` now uses merchant-level stream lookup instead of the dead streams query.
- **Files changed:** `queries.py`, `tools/recurring.py`, `tools/accounts.py`, `tests/test_recurring_management.py`, `tests/test_accounts.py`
- **Tests:** 162 passing (+2 net new)

---

## Test Files
| File | Tests | Description |
|------|-------|-------------|
| test_accounts.py | 25 | Enriched fields, payment details, due_day enrichment, merchant-level fallback |
| test_transactions.py | 33 | Recurring transactions, update_transaction, search, review |
| test_account_management.py | 19 | Create/update/delete account |
| test_recurring_management.py | 26 | get_merchant_details, get_recurring_streams (items-based), update/disable/create recurring |
| test_admin.py | 21 | Admin auth, status, reauth flows |
| test_categories.py | 6 | Category and category group tools |
| test_rules.py | 12 | Transaction rule CRUD |
| test_tags.py | 9 | Tag tools |
| **Total** | **162** | **All passing** |

## Commit History (Recent)
| Commit | Description |
|--------|-------------|
| (pending) | Fix #3: get_recurring_streams rewritten for items-based workaround |
| 853efeb | Due date write tools + enriched stream fields (latest, on origin main) |
| 66de23c | Due date read-side: enriched recurring + due_day in get_accounts |
| 1dff744 | Enriched get_accounts with payment fields |
| 2268dd5 | Issue #1 + #2: update_transaction fix, account lifecycle tools |
| (earlier) | Remote MCP server phases 1-7, original tool development |
