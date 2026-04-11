"""Monarch Money MCP Server - Main server implementation."""

import argparse
import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from mcp.server.auth.provider import AccessTokenT
from mcp.server.fastmcp import FastMCP
import mcp.types as types
from monarchmoney import MonarchMoney, MonarchMoneyEndpoints, RequireMFAException
from pydantic import BaseModel, Field
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


class MonarchConfig(BaseModel):
    """Configuration for Monarch Money connection."""

    email: Optional[str] = Field(default=None, description="Monarch Money email")
    password: Optional[str] = Field(default=None, description="Monarch Money password")
    session_file: str = Field(
        default="monarch_session.json", description="Session file path"
    )


async def get_monarch_client() -> MonarchMoney:
    """Get or create MonarchMoney client instance using secure session storage."""
    # Try to get authenticated client from secure session
    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("✅ Using authenticated client from secure keyring storage")
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

    raise RuntimeError("🔐 Authentication needed! Run: python login_setup.py")


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
    """Check if already authenticated with Monarch Money."""
    try:
        # Check if we have a token in the keyring
        token = secure_session.load_token()
        if token:
            status = "✅ Authentication token found in secure keyring storage\n"
        else:
            status = "❌ No authentication token found in keyring\n"

        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += f"📧 Environment email: {email}\n"

        status += (
            "\n💡 Try get_accounts to test connection or run login_setup.py if needed."
        )

        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool()
def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        # Check keyring access
        token = secure_session.load_token()
        if token:
            return f"✅ Token found in keyring (length: {len(token)})"
        else:
            return "❌ No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        return f"❌ Keyring access failed:\nError: {str(e)}\nType: {type(e)}\nTraceback:\n{error_details}"


# =============================================================================
# Custom GraphQL query for accounts with payment/credit fields
# =============================================================================
# Discovered via live API probing — these are the confirmed valid fields:
#   minimumPayment: works for credit cards and loans
#   apr: works for credit cards (None for loans)
#   interestRate: works for loans (None for credit cards)
#   limit: credit limit for credit cards (None for loans)
# Note: Fields like creditLimit, availableCredit, paymentDueDate, pastDueAmount
# do NOT exist in Monarch's schema (verified April 2026).

GET_ACCOUNTS_WITH_PAYMENT_FIELDS_QUERY = """
query GetAccountsWithPaymentFields {
  accounts {
    id
    displayName
    syncDisabled
    deactivatedAt
    isHidden
    isAsset
    mask
    createdAt
    updatedAt
    displayLastUpdatedAt
    currentBalance
    displayBalance
    includeInNetWorth
    hideFromList
    hideTransactionsFromReports
    dataProvider
    dataProviderAccountId
    isManual
    transactionsCount
    holdingsCount
    order
    logoUrl
    type {
      name
      display
      group
      __typename
    }
    subtype {
      name
      display
      __typename
    }
    credential {
      id
      updateRequired
      disconnectedFromDataProviderAt
      dataProvider
      institution {
        id
        name
        status
        __typename
      }
      __typename
    }
    institution {
      id
      name
      primaryColor
      url
      __typename
    }
    minimumPayment
    interestRate
    apr
    limit
    __typename
  }
}
"""


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money.

    Returns account details including balances, types, institutions, and
    when available, credit/loan payment information (minimum payment,
    APR, interest rate, credit limit).
    """
    try:
        from gql import gql

        async def _get_accounts():
            client = await get_monarch_client()

            # Try custom query with payment fields first
            try:
                query = gql(GET_ACCOUNTS_WITH_PAYMENT_FIELDS_QUERY)
                result = await client.gql_call(
                    operation="GetAccountsWithPaymentFields",
                    graphql_query=query,
                    variables={},
                )
                return result.get("accounts", []), True
            except Exception as e:
                logger.warning(
                    f"Custom account query failed, falling back to standard: {e}"
                )
                # Fall back to library's get_accounts() (no payment fields)
                result = await client.get_accounts()
                return result.get("accounts", []), False

        accounts, has_payment_fields = run_async(_get_accounts())

        # Format accounts for display
        account_list = []
        for account in accounts:
            account_info = {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "type": (account.get("type") or {}).get("name"),
                "type_display": (account.get("type") or {}).get("display"),
                "type_group": (account.get("type") or {}).get("group"),
                "subtype": (account.get("subtype") or {}).get("name"),
                "subtype_display": (account.get("subtype") or {}).get("display"),
                "balance": account.get("currentBalance"),
                "display_balance": account.get("displayBalance"),
                "institution": (account.get("institution") or {}).get("name"),
                "institution_url": (account.get("institution") or {}).get("url"),
                "is_active": account.get("isActive")
                if "isActive" in account
                else not account.get("deactivatedAt"),
                "is_asset": account.get("isAsset"),
                "is_manual": account.get("isManual"),
                "include_in_net_worth": account.get("includeInNetWorth"),
                "mask": account.get("mask"),
                "logo_url": account.get("logoUrl"),
                "data_provider": account.get("dataProvider")
                or (account.get("credential") or {}).get("dataProvider"),
                "last_updated": account.get("displayLastUpdatedAt"),
            }

            # Add payment details for credit/loan accounts when available
            if has_payment_fields:
                payment_info = {}
                for api_field, output_field in [
                    ("minimumPayment", "minimum_payment"),
                    ("apr", "apr"),
                    ("interestRate", "interest_rate"),
                    ("limit", "credit_limit"),
                ]:
                    value = account.get(api_field)
                    if value is not None:
                        payment_info[output_field] = value
                if payment_info:
                    account_info["payment_details"] = payment_info

            account_list.append(account_info)

        return json.dumps(account_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}")
        return f"Error getting accounts: {str(e)}"


@mcp.tool()
def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by
    """
    try:

        async def _get_transactions():
            client = await get_monarch_client()

            # Build filters
            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date
            if account_id:
                filters["account_id"] = account_id

            return await client.get_transactions(limit=limit, offset=offset, **filters)

        transactions = run_async(_get_transactions())

        # Format transactions for display
        transaction_list = []
        for txn in transactions.get("allTransactions", {}).get("results", []):
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "is_pending": txn.get("isPending", False),
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool()
def get_budgets() -> str:
    """Get budget information from Monarch Money."""
    try:

        async def _get_budgets():
            client = await get_monarch_client()
            return await client.get_budgets()

        budgets = run_async(_get_budgets())

        # Format budgets for display
        budget_list = []
        for budget in budgets.get("budgets", []):
            budget_info = {
                "id": budget.get("id"),
                "name": budget.get("name"),
                "amount": budget.get("amount"),
                "spent": budget.get("spent"),
                "remaining": budget.get("remaining"),
                "category": budget.get("category", {}).get("name"),
                "period": budget.get("period"),
            }
            budget_list.append(budget_info)

        return json.dumps(budget_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get budgets: {e}")
        return f"Error getting budgets: {str(e)}"


@mcp.tool()
def get_cashflow(
    start_date: Optional[str] = None, end_date: Optional[str] = None
) -> str:
    """
    Get cashflow analysis from Monarch Money.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    try:

        async def _get_cashflow():
            client = await get_monarch_client()

            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date

            return await client.get_cashflow(**filters)

        cashflow = run_async(_get_cashflow())

        return json.dumps(cashflow, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get cashflow: {e}")
        return f"Error getting cashflow: {str(e)}"


@mcp.tool()
def get_account_holdings(account_id: str) -> str:
    """
    Get investment holdings for a specific account.

    Args:
        account_id: The ID of the investment account
    """
    try:

        async def _get_holdings():
            client = await get_monarch_client()
            return await client.get_account_holdings(account_id)

        holdings = run_async(_get_holdings())

        return json.dumps(holdings, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get account holdings: {e}")
        return f"Error getting account holdings: {str(e)}"


@mcp.tool()
def create_transaction(
    account_id: str,
    amount: float,
    description: str,
    date: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        description: Transaction description
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        merchant_name: Optional merchant name
    """
    try:

        async def _create_transaction():
            client = await get_monarch_client()

            transaction_data = {
                "account_id": account_id,
                "amount": amount,
                "description": description,
                "date": date,
            }

            if category_id:
                transaction_data["category_id"] = category_id
            if merchant_name:
                transaction_data["merchant_name"] = merchant_name

            return await client.create_transaction(**transaction_data)

        result = run_async(_create_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        description: New transaction description
        category_id: New category ID
        date: New transaction date in YYYY-MM-DD format
    """
    try:

        async def _update_transaction():
            client = await get_monarch_client()

            update_data = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if description is not None:
                update_data["description"] = description
            if category_id is not None:
                update_data["category_id"] = category_id
            if date is not None:
                update_data["date"] = date

            return await client.update_transaction(**update_data)

        result = run_async(_update_transaction())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


@mcp.tool()
def set_transaction_category(
    transaction_id: str,
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Set the category for a transaction and optionally mark it as reviewed.

    This is the primary tool for categorizing transactions during review.
    Use get_categories() first to see available categories.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The ID of the category to assign (use get_categories to find IDs)
        mark_reviewed: Whether to also mark the transaction as reviewed (default: True)

    Returns:
        Updated transaction details.
    """
    try:

        async def _set_category():
            client = await get_monarch_client()

            update_params = {
                "transaction_id": transaction_id,
                "category_id": category_id,
            }

            if mark_reviewed:
                update_params["needs_review"] = False

            return await client.update_transaction(**update_params)

        result = run_async(_set_category())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction category: {e}")
        return f"Error setting category: {str(e)}"


@mcp.tool()
def update_transaction_notes(
    transaction_id: str,
    notes: str,
    receipt_url: Optional[str] = None,
) -> str:
    """
    Update the notes/memo for a transaction.

    Suggested format: [Receipt: URL] Description
    If receipt_url is provided, it will be prepended to the notes.

    Args:
        transaction_id: The ID of the transaction to update
        notes: The note/memo text to add
        receipt_url: Optional URL to a receipt (will be formatted as [Receipt: URL])

    Returns:
        Updated transaction details.
    """
    try:

        async def _update_notes():
            client = await get_monarch_client()

            # Format notes with receipt URL if provided
            if receipt_url:
                formatted_notes = f"[Receipt: {receipt_url}] {notes}"
            else:
                formatted_notes = notes

            return await client.update_transaction(
                transaction_id=transaction_id,
                notes=formatted_notes,
            )

        result = run_async(_update_notes())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction notes: {e}")
        return f"Error updating notes: {str(e)}"


@mcp.tool()
def mark_transaction_reviewed(
    transaction_id: str,
) -> str:
    """
    Mark a transaction as reviewed (clears the needs_review flag).

    Use this after reviewing a transaction that doesn't need category changes.

    Args:
        transaction_id: The ID of the transaction to mark as reviewed

    Returns:
        Updated transaction details.
    """
    try:

        async def _mark_reviewed():
            client = await get_monarch_client()

            return await client.update_transaction(
                transaction_id=transaction_id,
                needs_review=False,
            )

        result = run_async(_mark_reviewed())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to mark transaction as reviewed: {e}")
        return f"Error marking reviewed: {str(e)}"


@mcp.tool()
def bulk_categorize_transactions(
    transaction_ids: List[str],
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Apply the same category to multiple transactions at once.

    This is useful for categorizing similar transactions in bulk,
    such as all purchases from the same merchant.

    Args:
        transaction_ids: List of transaction IDs to categorize
        category_id: The category ID to apply to all transactions
        mark_reviewed: Whether to also mark transactions as reviewed (default: True)

    Returns:
        Summary of results including success/failure counts.
    """
    try:

        async def _bulk_categorize():
            client = await get_monarch_client()

            results = {
                "total": len(transaction_ids),
                "successful": 0,
                "failed": 0,
                "errors": [],
            }

            for txn_id in transaction_ids:
                try:
                    update_params = {
                        "transaction_id": txn_id,
                        "category_id": category_id,
                    }
                    if mark_reviewed:
                        update_params["needs_review"] = False

                    await client.update_transaction(**update_params)
                    results["successful"] += 1
                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append(
                        {
                            "transaction_id": txn_id,
                            "error": str(e),
                        }
                    )

            return results

        result = run_async(_bulk_categorize())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to bulk categorize transactions: {e}")
        return f"Error in bulk categorization: {str(e)}"


@mcp.tool()
def get_tags() -> str:
    """
    Get all transaction tags from Monarch Money.

    Returns a list of tags with their colors and transaction counts.
    Use this to see available tags before applying them to transactions.
    """
    try:

        async def _get_tags():
            client = await get_monarch_client()
            return await client.get_transaction_tags()

        tags_data = run_async(_get_tags())

        # Format tags for display
        tag_list = []
        for tag in tags_data.get("householdTransactionTags", []):
            tag_info = {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "color": tag.get("color"),
                "order": tag.get("order"),
                "transaction_count": tag.get("transactionCount", 0),
            }
            tag_list.append(tag_info)

        return json.dumps(tag_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get tags: {e}")
        return f"Error getting tags: {str(e)}"


@mcp.tool()
def set_transaction_tags(
    transaction_id: str,
    tag_ids: List[str],
) -> str:
    """
    Set tags on a transaction.

    Note: This REPLACES all existing tags on the transaction.
    To add a tag, include both existing and new tag IDs.
    To remove all tags, pass an empty list.

    Args:
        transaction_id: The ID of the transaction to tag
        tag_ids: List of tag IDs to apply (use get_tags to find IDs)

    Returns:
        Updated transaction details.
    """
    try:

        async def _set_tags():
            client = await get_monarch_client()
            return await client.set_transaction_tags(
                transaction_id=transaction_id,
                tag_ids=tag_ids,
            )

        result = run_async(_set_tags())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to set transaction tags: {e}")
        return f"Error setting tags: {str(e)}"


@mcp.tool()
def create_tag(
    name: str,
    color: str = "#19D2A5",
) -> str:
    """
    Create a new transaction tag.

    Args:
        name: Name for the new tag
        color: Hex color code for the tag (default: "#19D2A5" - teal)
               Examples: "#FF5733" (red-orange), "#3498DB" (blue), "#9B59B6" (purple)

    Returns:
        The created tag details including its ID.
    """
    try:

        async def _create_tag():
            client = await get_monarch_client()
            return await client.create_transaction_tag(
                name=name,
                color=color,
            )

        result = run_async(_create_tag())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        return f"Error creating tag: {str(e)}"


@mcp.tool()
def search_transactions(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category_ids: Optional[List[str]] = None,
    account_ids: Optional[List[str]] = None,
    tag_ids: Optional[List[str]] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
) -> str:
    """
    Search and filter transactions with comprehensive filtering options.

    This is the most flexible transaction query tool, supporting all available filters.

    Args:
        search: Text to search for in transaction descriptions/merchants
        limit: Maximum number of transactions to return (default: 100)
        offset: Number of transactions to skip for pagination (default: 0)
        start_date: Filter start date in YYYY-MM-DD format
        end_date: Filter end date in YYYY-MM-DD format
        category_ids: List of category IDs to filter by
        account_ids: List of account IDs to filter by
        tag_ids: List of tag IDs to filter by
        has_attachments: Filter for transactions with/without attachments
        has_notes: Filter for transactions with/without notes
        hidden_from_reports: Filter for transactions hidden/shown in reports
        is_split: Filter for split/non-split transactions
        is_recurring: Filter for recurring/non-recurring transactions

    Returns:
        List of matching transactions with full details.
    """
    try:

        async def _search_transactions():
            client = await get_monarch_client()

            # Build filters dict with only non-None values
            filters = {"limit": limit, "offset": offset}

            if search:
                filters["search"] = search
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date
            if category_ids:
                filters["category_ids"] = category_ids
            if account_ids:
                filters["account_ids"] = account_ids
            if tag_ids:
                filters["tag_ids"] = tag_ids
            if has_attachments is not None:
                filters["has_attachments"] = has_attachments
            if has_notes is not None:
                filters["has_notes"] = has_notes
            if hidden_from_reports is not None:
                filters["hidden_from_reports"] = hidden_from_reports
            if is_split is not None:
                filters["is_split"] = is_split
            if is_recurring is not None:
                filters["is_recurring"] = is_recurring

            return await client.get_transactions(**filters)

        transactions_data = run_async(_search_transactions())

        # Format transactions with full details
        transaction_list = []
        for txn in transactions_data.get("allTransactions", {}).get("results", []):
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "original_name": txn.get("plaidName") or txn.get("originalName"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "category_id": txn.get("category", {}).get("id")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName")
                if txn.get("account")
                else None,
                "account_id": txn.get("account", {}).get("id")
                if txn.get("account")
                else None,
                "notes": txn.get("notes"),
                "needs_review": txn.get("needsReview", False),
                "is_pending": txn.get("pending", False),
                "hide_from_reports": txn.get("hideFromReports", False),
                "is_split": txn.get("isSplitTransaction", False),
                "is_recurring": txn.get("isRecurring", False),
                "has_attachments": bool(txn.get("attachments")),
                "tags": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in txn.get("tags", [])
                ]
                if txn.get("tags")
                else [],
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to search transactions: {e}")
        return f"Error searching transactions: {str(e)}"


@mcp.tool()
def get_transaction_details(
    transaction_id: str,
) -> str:
    """
    Get full details for a specific transaction.

    Returns comprehensive information including attachments, splits, tags, and more.

    Args:
        transaction_id: The ID of the transaction to get details for

    Returns:
        Complete transaction details.
    """
    try:

        async def _get_details():
            client = await get_monarch_client()
            return await client.get_transaction_details(transaction_id=transaction_id)

        result = run_async(_get_details())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction details: {e}")
        return f"Error getting transaction details: {str(e)}"


@mcp.tool()
def delete_transaction(
    transaction_id: str,
) -> str:
    """
    Delete a transaction from Monarch Money.

    Warning: This action cannot be undone.

    Args:
        transaction_id: The ID of the transaction to delete

    Returns:
        Confirmation of deletion.
    """
    try:

        async def _delete():
            client = await get_monarch_client()
            return await client.delete_transaction(transaction_id=transaction_id)

        result = run_async(_delete())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return f"Error deleting transaction: {str(e)}"


@mcp.tool()
def get_recurring_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get upcoming recurring transactions.

    Returns scheduled recurring transactions with their merchants, amounts, and accounts.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to start of current month)
        end_date: End date in YYYY-MM-DD format (defaults to end of current month)

    Returns:
        List of upcoming recurring transactions.
    """
    try:

        async def _get_recurring():
            client = await get_monarch_client()

            filters = {}
            if start_date:
                filters["start_date"] = start_date
            if end_date:
                filters["end_date"] = end_date

            return await client.get_recurring_transactions(**filters)

        result = run_async(_get_recurring())

        # Format recurring transactions
        recurring_list = []
        for item in result.get("recurringTransactionItems", []):
            recurring_info = {
                "date": item.get("date"),
                "amount": item.get("amount"),
                "is_past": item.get("isPast", False),
                "transaction_id": item.get("transactionId"),
                "stream": {
                    "id": item.get("stream", {}).get("id"),
                    "frequency": item.get("stream", {}).get("frequency"),
                    "amount": item.get("stream", {}).get("amount"),
                    "is_approximate": item.get("stream", {}).get(
                        "isApproximate", False
                    ),
                    "merchant": item.get("stream", {}).get("merchant", {}).get("name")
                    if item.get("stream", {}).get("merchant")
                    else None,
                }
                if item.get("stream")
                else None,
                "category": item.get("category", {}).get("name")
                if item.get("category")
                else None,
                "account": item.get("account", {}).get("displayName")
                if item.get("account")
                else None,
            }
            recurring_list.append(recurring_info)

        return json.dumps(recurring_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get recurring transactions: {e}")
        return f"Error getting recurring transactions: {str(e)}"


# =============================================================================
# Transaction Rules API (reverse-engineered from Monarch web app)
# =============================================================================

# GraphQL query for getting transaction rules
GET_TRANSACTION_RULES_QUERY = """
query GetTransactionRules {
  transactionRules {
    id
    order
    merchantCriteriaUseOriginalStatement
    merchantCriteria {
      operator
      value
      __typename
    }
    originalStatementCriteria {
      operator
      value
      __typename
    }
    merchantNameCriteria {
      operator
      value
      __typename
    }
    amountCriteria {
      operator
      isExpense
      value
      valueRange {
        lower
        upper
        __typename
      }
      __typename
    }
    categoryIds
    accountIds
    categories {
      id
      name
      icon
      __typename
    }
    accounts {
      id
      displayName
      __typename
    }
    setMerchantAction {
      id
      name
      __typename
    }
    setCategoryAction {
      id
      name
      icon
      __typename
    }
    addTagsAction {
      id
      name
      color
      __typename
    }
    linkGoalAction {
      id
      name
      __typename
    }
    setHideFromReportsAction
    reviewStatusAction
    recentApplicationCount
    lastAppliedAt
    __typename
  }
}
"""

CREATE_TRANSACTION_RULE_MUTATION = """
mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
  createTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

UPDATE_TRANSACTION_RULE_MUTATION = """
mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
  updateTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

DELETE_TRANSACTION_RULE_MUTATION = """
mutation Common_DeleteTransactionRule($id: ID!) {
  deleteTransactionRule(id: $id) {
    deleted
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""


@mcp.tool()
def get_transaction_rules() -> str:
    """
    Get all transaction auto-categorization rules from Monarch Money.

    Returns a list of rules with their conditions and actions.
    Rules automatically categorize transactions based on merchant, amount, etc.
    """
    try:
        from gql import gql

        async def _get_rules():
            client = await get_monarch_client()
            query = gql(GET_TRANSACTION_RULES_QUERY)
            return await client.gql_call(
                operation="GetTransactionRules",
                graphql_query=query,
                variables={},
            )

        result = run_async(_get_rules())

        # Format rules for display
        rules_list = []
        for rule in result.get("transactionRules", []):
            rule_info = {
                "id": rule.get("id"),
                "order": rule.get("order"),
                # Criteria (conditions)
                "merchant_criteria": rule.get("merchantCriteria"),
                "merchant_name_criteria": rule.get("merchantNameCriteria"),
                "original_statement_criteria": rule.get("originalStatementCriteria"),
                "amount_criteria": rule.get("amountCriteria"),
                "category_ids": rule.get("categoryIds"),
                "account_ids": rule.get("accountIds"),
                "use_original_statement": rule.get(
                    "merchantCriteriaUseOriginalStatement"
                ),
                # Actions
                "set_category_action": {
                    "id": rule.get("setCategoryAction", {}).get("id"),
                    "name": rule.get("setCategoryAction", {}).get("name"),
                }
                if rule.get("setCategoryAction")
                else None,
                "set_merchant_action": {
                    "id": rule.get("setMerchantAction", {}).get("id"),
                    "name": rule.get("setMerchantAction", {}).get("name"),
                }
                if rule.get("setMerchantAction")
                else None,
                "add_tags_action": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in rule.get("addTagsAction", [])
                ]
                if rule.get("addTagsAction")
                else None,
                "link_goal_action": rule.get("linkGoalAction"),
                "hide_from_reports_action": rule.get("setHideFromReportsAction"),
                "review_status_action": rule.get("reviewStatusAction"),
                # Stats
                "recent_application_count": rule.get("recentApplicationCount"),
                "last_applied_at": rule.get("lastAppliedAt"),
            }
            rules_list.append(rule_info)

        return json.dumps(rules_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction rules: {e}")
        return f"Error getting transaction rules: {str(e)}"


@mcp.tool()
def create_transaction_rule(
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    apply_to_existing: bool = False,
) -> str:
    """
    Create a new transaction auto-categorization rule.

    Rules automatically categorize future transactions based on conditions.

    Args:
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign (use get_categories for IDs)
        set_merchant_name: Merchant name to set on matching transactions
        add_tag_ids: List of tag IDs to add (use get_tags for IDs)
        hide_from_reports: Whether to hide matching transactions from reports
        review_status: Review status to set ("needs_review" or null)
        account_ids: Limit rule to specific account IDs
        apply_to_existing: Whether to apply rule to existing transactions

    Returns:
        Result of rule creation.

    Example:
        Create rule: "Amazon purchases → Shopping category"
        create_transaction_rule(
            merchant_criteria_operator="contains",
            merchant_criteria_value="amazon",
            set_category_id="cat_123"
        )
    """
    try:
        from gql import gql

        async def _create_rule():
            client = await get_monarch_client()

            # Build input
            rule_input: Dict[str, Any] = {
                "applyToExistingTransactions": apply_to_existing,
            }

            # Merchant criteria
            if merchant_criteria_operator and merchant_criteria_value:
                rule_input["merchantNameCriteria"] = [
                    {
                        "operator": merchant_criteria_operator,
                        "value": merchant_criteria_value,
                    }
                ]

            # Amount criteria
            if amount_operator and amount_value is not None:
                rule_input["amountCriteria"] = {
                    "operator": amount_operator,
                    "isExpense": amount_is_expense,
                    "value": amount_value,
                    "valueRange": None,
                }

            # Account filter
            if account_ids:
                rule_input["accountIds"] = account_ids

            # Actions
            if set_category_id:
                rule_input["setCategoryAction"] = set_category_id
            if set_merchant_name:
                rule_input["setMerchantAction"] = set_merchant_name
            if add_tag_ids:
                rule_input["addTagsAction"] = add_tag_ids
            if hide_from_reports is not None:
                rule_input["setHideFromReportsAction"] = hide_from_reports
            if review_status:
                rule_input["reviewStatusAction"] = review_status

            query = gql(CREATE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_CreateTransactionRuleMutationV2",
                graphql_query=query,
                variables={"input": rule_input},
            )

        result = run_async(_create_rule())

        # Check for errors
        errors = result.get("createTransactionRuleV2", {}).get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps(
            {"success": True, "message": "Rule created successfully"}, indent=2
        )
    except Exception as e:
        logger.error(f"Failed to create transaction rule: {e}")
        return f"Error creating transaction rule: {str(e)}"


@mcp.tool()
def update_transaction_rule(
    rule_id: str,
    merchant_criteria_operator: Optional[str] = None,
    merchant_criteria_value: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
    amount_is_expense: bool = True,
    set_category_id: Optional[str] = None,
    set_merchant_name: Optional[str] = None,
    add_tag_ids: Optional[List[str]] = None,
    hide_from_reports: Optional[bool] = None,
    review_status: Optional[str] = None,
    account_ids: Optional[List[str]] = None,
    apply_to_existing: bool = False,
) -> str:
    """
    Update an existing transaction rule.

    Args:
        rule_id: The ID of the rule to update (use get_transaction_rules to find IDs)
        merchant_criteria_operator: How to match merchant ("eq", "contains")
        merchant_criteria_value: Merchant name/pattern to match
        amount_operator: Amount comparison ("gt", "lt", "eq", "between")
        amount_value: Amount threshold value
        amount_is_expense: Whether amount is expense (negative) or income
        set_category_id: Category ID to assign
        set_merchant_name: Merchant name to set
        add_tag_ids: List of tag IDs to add
        hide_from_reports: Whether to hide from reports
        review_status: Review status to set
        account_ids: Limit rule to specific accounts
        apply_to_existing: Apply changes to existing transactions

    Returns:
        Result of rule update.
    """
    try:
        from gql import gql

        async def _update_rule():
            client = await get_monarch_client()

            # Build input
            rule_input: Dict[str, Any] = {
                "id": rule_id,
                "applyToExistingTransactions": apply_to_existing,
            }

            # Merchant criteria
            if merchant_criteria_operator and merchant_criteria_value:
                rule_input["merchantNameCriteria"] = [
                    {
                        "operator": merchant_criteria_operator,
                        "value": merchant_criteria_value,
                    }
                ]

            # Amount criteria
            if amount_operator and amount_value is not None:
                rule_input["amountCriteria"] = {
                    "operator": amount_operator,
                    "isExpense": amount_is_expense,
                    "value": amount_value,
                    "valueRange": None,
                }

            # Account filter
            if account_ids:
                rule_input["accountIds"] = account_ids

            # Actions
            if set_category_id:
                rule_input["setCategoryAction"] = set_category_id
            if set_merchant_name:
                rule_input["setMerchantAction"] = set_merchant_name
            if add_tag_ids:
                rule_input["addTagsAction"] = add_tag_ids
            if hide_from_reports is not None:
                rule_input["setHideFromReportsAction"] = hide_from_reports
            if review_status:
                rule_input["reviewStatusAction"] = review_status

            query = gql(UPDATE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_UpdateTransactionRuleMutationV2",
                graphql_query=query,
                variables={"input": rule_input},
            )

        result = run_async(_update_rule())

        # Check for errors
        errors = result.get("updateTransactionRuleV2", {}).get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps(
            {"success": True, "message": "Rule updated successfully"}, indent=2
        )
    except Exception as e:
        logger.error(f"Failed to update transaction rule: {e}")
        return f"Error updating transaction rule: {str(e)}"


@mcp.tool()
def delete_transaction_rule(
    rule_id: str,
) -> str:
    """
    Delete a transaction rule.

    Args:
        rule_id: The ID of the rule to delete (use get_transaction_rules to find IDs)

    Returns:
        Confirmation of deletion.
    """
    try:
        from gql import gql

        async def _delete_rule():
            client = await get_monarch_client()

            query = gql(DELETE_TRANSACTION_RULE_MUTATION)
            return await client.gql_call(
                operation="Common_DeleteTransactionRule",
                graphql_query=query,
                variables={"id": rule_id},
            )

        result = run_async(_delete_rule())

        # Check result
        delete_result = result.get("deleteTransactionRule", {})
        if delete_result.get("deleted"):
            return json.dumps(
                {"success": True, "message": "Rule deleted successfully"}, indent=2
            )

        errors = delete_result.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps({"success": False, "message": "Unknown error"}, indent=2)
    except Exception as e:
        logger.error(f"Failed to delete transaction rule: {e}")
        return f"Error deleting transaction rule: {str(e)}"


@mcp.tool()
def refresh_accounts() -> str:
    """Request account data refresh from financial institutions."""
    try:

        async def _refresh_accounts():
            client = await get_monarch_client()
            return await client.request_accounts_refresh()

        result = run_async(_refresh_accounts())

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to refresh accounts: {e}")
        return f"Error refreshing accounts: {str(e)}"


@mcp.tool()
def get_categories() -> str:
    """
    Get all transaction categories from Monarch Money.

    Returns a list of categories with their groups, icons, and metadata.
    Useful for selecting a category when categorizing transactions.
    """
    try:

        async def _get_categories():
            client = await get_monarch_client()
            return await client.get_transaction_categories()

        categories_data = run_async(_get_categories())

        # Format categories for display
        category_list = []
        for cat in categories_data.get("categories", []):
            category_info = {
                "id": cat.get("id"),
                "name": cat.get("name"),
                "icon": cat.get("icon"),
                "group": cat.get("group", {}).get("name") if cat.get("group") else None,
                "group_id": cat.get("group", {}).get("id")
                if cat.get("group")
                else None,
                "is_system_category": cat.get("isSystemCategory", False),
                "is_disabled": cat.get("isDisabled", False),
            }
            category_list.append(category_info)

        return json.dumps(category_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        return f"Error getting categories: {str(e)}"


@mcp.tool()
def get_category_groups() -> str:
    """
    Get all transaction category groups from Monarch Money.

    Returns groups like Income, Expenses, etc. with their associated categories.
    """
    try:

        async def _get_category_groups():
            client = await get_monarch_client()
            return await client.get_transaction_category_groups()

        groups_data = run_async(_get_category_groups())

        # Format category groups for display
        group_list = []
        for group in groups_data.get("categoryGroups", []):
            group_info = {
                "id": group.get("id"),
                "name": group.get("name"),
                "type": group.get("type"),
                "budget_variability": group.get("budgetVariability"),
                "group_level_budgeting_enabled": group.get(
                    "groupLevelBudgetingEnabled", False
                ),
                "categories": [
                    {
                        "id": cat.get("id"),
                        "name": cat.get("name"),
                        "icon": cat.get("icon"),
                    }
                    for cat in group.get("categories", [])
                ],
            }
            group_list.append(group_info)

        return json.dumps(group_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get category groups: {e}")
        return f"Error getting category groups: {str(e)}"


@mcp.tool()
def get_transactions_needing_review(
    needs_review: bool = True,
    days: Optional[int] = None,
    uncategorized_only: bool = False,
    without_notes_only: bool = False,
    limit: int = 100,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions that need review based on various criteria.

    This is the primary tool for finding transactions to categorize and review.

    Args:
        needs_review: Filter for transactions flagged as needing review (default: True)
        days: Only include transactions from the last N days (e.g., 7 for last week)
        uncategorized_only: Only include transactions without a category assigned
        without_notes_only: Only include transactions without notes/memos
        limit: Maximum number of transactions to return (default: 100)
        account_id: Filter by specific account ID

    Returns:
        List of transactions matching the criteria with full details.
    """
    try:
        from datetime import datetime, timedelta

        async def _get_transactions():
            client = await get_monarch_client()

            # Build filters
            filters = {"limit": limit}

            # Date range filter
            if days:
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime(
                    "%Y-%m-%d"
                )
                filters["start_date"] = start_date
                filters["end_date"] = end_date

            if account_id:
                filters["account_ids"] = [account_id]

            # Note: has_notes filter (if supported by API)
            if without_notes_only:
                filters["has_notes"] = False

            return await client.get_transactions(**filters)

        transactions_data = run_async(_get_transactions())

        # Post-filter transactions based on criteria
        transaction_list = []
        for txn in transactions_data.get("allTransactions", {}).get("results", []):
            # Filter by needs_review
            if needs_review and not txn.get("needsReview", False):
                continue

            # Filter by uncategorized (no category or null category)
            if uncategorized_only:
                category = txn.get("category")
                if category and category.get("id"):
                    continue

            # Format transaction with full details
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "original_name": txn.get("plaidName") or txn.get("originalName"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "category_id": txn.get("category", {}).get("id")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName")
                if txn.get("account")
                else None,
                "account_id": txn.get("account", {}).get("id")
                if txn.get("account")
                else None,
                "notes": txn.get("notes"),
                "needs_review": txn.get("needsReview", False),
                "is_pending": txn.get("pending", False),
                "hide_from_reports": txn.get("hideFromReports", False),
                "tags": [
                    {"id": tag.get("id"), "name": tag.get("name")}
                    for tag in txn.get("tags", [])
                ]
                if txn.get("tags")
                else [],
            }
            transaction_list.append(transaction_info)

        return json.dumps(transaction_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions needing review: {e}")
        return f"Error getting transactions: {str(e)}"


def _configure_remote_auth():
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

    LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monarch MCP Server - Authorize</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }}
        .container {{
            background: #16213e;
            border-radius: 12px;
            padding: 2rem;
            max-width: 400px;
            width: 90%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        h1 {{
            font-size: 1.4rem;
            margin: 0 0 0.5rem 0;
            color: #4ecca3;
        }}
        p {{
            font-size: 0.9rem;
            color: #a0a0b0;
            margin: 0 0 1.5rem 0;
        }}
        .warning {{
            background: rgba(255, 193, 7, 0.1);
            border: 1px solid rgba(255, 193, 7, 0.3);
            border-radius: 8px;
            padding: 0.75rem;
            margin-bottom: 1.5rem;
            font-size: 0.85rem;
            color: #ffc107;
        }}
        label {{
            display: block;
            font-size: 0.85rem;
            margin-bottom: 0.4rem;
            color: #b0b0c0;
        }}
        input[type="password"] {{
            width: 100%;
            padding: 0.7rem;
            border: 1px solid #2a2a4a;
            border-radius: 8px;
            background: #0f0f23;
            color: #e0e0e0;
            font-size: 1rem;
            box-sizing: border-box;
            margin-bottom: 1rem;
        }}
        input[type="password"]:focus {{
            outline: none;
            border-color: #4ecca3;
        }}
        button {{
            width: 100%;
            padding: 0.75rem;
            background: #4ecca3;
            color: #1a1a2e;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
        }}
        button:hover {{
            background: #3dba8f;
        }}
        .error {{
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 8px;
            padding: 0.75rem;
            margin-bottom: 1rem;
            font-size: 0.85rem;
            color: #ef4444;
        }}
    </style>
</head>
<body>
    <div class="container">
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
    </div>
</body>
</html>"""

    @mcp.custom_route("/auth/login", methods=["GET"])
    async def auth_login_get(request: Request) -> Response:
        """Render the password gate login form."""
        session = request.query_params.get("session", "")
        if not session:
            return HTMLResponse(
                "<h1>400 Bad Request</h1><p>Missing session parameter.</p>",
                status_code=400,
            )
        html = LOGIN_PAGE_HTML.format(session=session, error_html="")
        return HTMLResponse(html)

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
            html = LOGIN_PAGE_HTML.format(session=session_id, error_html=error_html)
            return HTMLResponse(html, status_code=401)

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
        register_stdio_tools()
        logger.info("Starting Monarch Money MCP Server (stdio mode)...")
        mcp.run(transport=transport)
    else:
        # Remote mode: configure HTTP settings, OAuth, and security middleware
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        _configure_remote_auth()
        logger.info(
            f"Starting Monarch Money MCP Server (streamable-http mode on {args.host}:{args.port})..."
        )
        _run_remote_server()


def _run_remote_server():
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


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
