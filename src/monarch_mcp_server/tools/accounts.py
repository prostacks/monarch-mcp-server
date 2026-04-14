"""Account tools for the Monarch Money MCP Server."""

import json
import logging
from typing import Any, Dict, Optional

from monarch_mcp_server.server import mcp, run_async, get_monarch_client
from monarch_mcp_server.queries import (
    GET_ACCOUNTS_WITH_PAYMENT_FIELDS_QUERY,
    GET_MERCHANT_DETAILS_QUERY,
    GET_RECURRING_TRANSACTIONS_ENRICHED_QUERY,
    UPDATE_ACCOUNT_WITH_PAYMENT_FIELDS_MUTATION,
)

logger = logging.getLogger(__name__)


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Monarch Money.

    Returns account details including balances, types, institutions, and
    when available, credit/loan payment information (minimum payment,
    APR, interest rate, credit limit, due day).

    For credit and loan accounts, the due_day field (day of month when
    payment is typically due) is automatically populated from recurring
    transaction data when available.
    """
    try:
        from datetime import datetime, timedelta

        from gql import gql

        credit_loan_types = {"credit", "loan"}

        async def _get_accounts_with_due_days():
            client = await get_monarch_client()

            # Step 1: Fetch accounts (custom query with payment fields, or fallback)
            try:
                query = gql(GET_ACCOUNTS_WITH_PAYMENT_FIELDS_QUERY)
                result = await client.gql_call(
                    operation="GetAccountsWithPaymentFields",
                    graphql_query=query,
                    variables={},
                )
                accounts = result.get("accounts", [])
                has_payment_fields = True
            except Exception as e:
                logger.warning(
                    f"Custom account query failed, falling back to standard: {e}"
                )
                result = await client.get_accounts()
                accounts = result.get("accounts", [])
                has_payment_fields = False

            # Step 2: Format accounts and identify credit/loan accounts
            account_list = []
            accounts_needing_due_day = set()

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

                # Track credit/loan accounts for due_day enrichment
                type_name = (account.get("type") or {}).get("name", "")
                if type_name and type_name.lower() in credit_loan_types:
                    acct_id = account.get("id")
                    if acct_id:
                        accounts_needing_due_day.add(acct_id)

                account_list.append(account_info)

            # Step 3: Enrich with due_day from recurring transactions
            if accounts_needing_due_day:
                try:
                    due_day_map = await _fetch_due_days(
                        client, accounts_needing_due_day
                    )
                    for account_info in account_list:
                        acct_id = account_info.get("id")
                        if acct_id in due_day_map:
                            if "payment_details" not in account_info:
                                account_info["payment_details"] = {}
                            account_info["payment_details"].update(due_day_map[acct_id])
                except Exception as e:
                    logger.warning(f"Failed to enrich accounts with due days: {e}")

            return account_list

        async def _fetch_due_days(client, account_ids_needing_due_day):
            """Fetch recurring transactions and extract due days per account.

            Extracts the day-of-month from stream.baseDate (the authoritative
            billing/due date configured on the recurring stream). Falls back to
            item.date when baseDate is not available.

            Uses a two-phase approach:
            1. Date-windowed recurringTransactionItems (catches most accounts)
            2. Merchant-level lookup for remaining accounts — fetches recent
               transactions on each unresolved account to find merchants, then
               queries each merchant for a recurringTransactionStream. This
               catches accounts like Lending Club that have a merchant with a
               stream but no recurring items in any date window.
            """
            from datetime import datetime, timedelta

            now = datetime.now()
            start = now.strftime("%Y-%m-01")
            end_dt = now + timedelta(days=60)
            end = end_dt.strftime("%Y-%m-28")

            # Phase 1: Date-windowed items query
            try:
                query = gql(GET_RECURRING_TRANSACTIONS_ENRICHED_QUERY)
                result = await client.gql_call(
                    operation="Web_GetUpcomingRecurringTransactionItems",
                    graphql_query=query,
                    variables={
                        "startDate": start,
                        "endDate": end,
                        "filters": {},
                    },
                )
            except Exception:
                try:
                    result = await client.get_recurring_transactions(
                        start_date=start, end_date=end
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch recurring transactions for due days: {e}"
                    )
                    result = {"recurringTransactionItems": []}

            # Build account_id -> recurring info lookup from items
            due_day_map = {}
            for item in result.get("recurringTransactionItems", []):
                account = item.get("account") or {}
                acct_id = account.get("id")
                if not acct_id or acct_id not in account_ids_needing_due_day:
                    continue
                if acct_id in due_day_map:
                    continue

                stream = item.get("stream") or {}
                merchant = stream.get("merchant") or {}
                date_str = stream.get("baseDate") or item.get("date")
                if not date_str:
                    continue
                try:
                    day = int(date_str.split("-")[2])
                    info = {"due_day": day}
                    if merchant.get("id"):
                        info["recurring_merchant_id"] = merchant["id"]
                    if stream.get("id"):
                        info["recurring_stream_id"] = stream["id"]
                    due_day_map[acct_id] = info
                except (IndexError, ValueError):
                    continue

            # Phase 2: Merchant-level fallback for accounts still missing
            remaining = account_ids_needing_due_day - set(due_day_map.keys())
            if remaining:
                try:
                    merchant_query = gql(GET_MERCHANT_DETAILS_QUERY)
                    for acct_id in remaining:
                        try:
                            # Get recent transactions for this account
                            txns = await client.get_transactions(
                                limit=10, account_ids=[acct_id]
                            )
                            results = txns.get("allTransactions", {}).get("results", [])
                            # Check each merchant for a recurring stream
                            seen_merchants = set()
                            for txn in results:
                                merchant = txn.get("merchant") or {}
                                m_id = merchant.get("id")
                                if not m_id or m_id in seen_merchants:
                                    continue
                                seen_merchants.add(m_id)

                                m_result = await client.gql_call(
                                    operation="Common_GetEditMerchant",
                                    graphql_query=merchant_query,
                                    variables={"merchantId": m_id},
                                )
                                m_data = m_result.get("merchant") or {}
                                stream = m_data.get("recurringTransactionStream") or {}
                                date_str = stream.get("baseDate")
                                if not date_str:
                                    continue
                                try:
                                    day = int(date_str.split("-")[2])
                                    info = {"due_day": day}
                                    info["recurring_merchant_id"] = m_id
                                    if stream.get("id"):
                                        info["recurring_stream_id"] = stream["id"]
                                    due_day_map[acct_id] = info
                                    break  # Found a stream, done with this account
                                except (IndexError, ValueError):
                                    continue
                        except Exception as e:
                            logger.debug(
                                f"Merchant fallback failed for account {acct_id}: {e}"
                            )
                            continue
                except Exception as e:
                    logger.warning(f"Failed merchant-level due day fallback: {e}")

            return due_day_map

        account_list = run_async(_get_accounts_with_due_days())
        return json.dumps(account_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}")
        return f"Error getting accounts: {str(e)}"


@mcp.tool()
def create_account(
    name: str,
    account_type: str,
    account_subtype: str,
    balance: float = 0.0,
    include_in_net_worth: bool = True,
) -> str:
    """
    Create a new manual account in Monarch Money.

    Only manual accounts can be created via the API. Connected (Plaid/bank-synced)
    accounts must be added through the Monarch Money web interface.

    Payment details (minimum payment, interest rate, APR) cannot be set at creation
    time. Use update_account after creation to set those fields.

    Args:
        name: Display name for the account (e.g. "Ford Credit Auto Loan")
        account_type: Account type — "loan", "credit", or "depository"
        account_subtype: Account subtype — e.g. "checking", "savings", "credit_card", "auto", "personal"
        balance: Starting balance (default 0.0)
        include_in_net_worth: Whether to include in net worth calculation (default True)

    Returns:
        Created account details including id, name, type, and balance.
    """
    try:

        async def _create_account():
            client = await get_monarch_client()
            return await client.create_manual_account(
                account_type=account_type,
                account_sub_type=account_subtype,
                is_in_net_worth=include_in_net_worth,
                account_name=name,
                account_balance=balance,
            )

        result = run_async(_create_account())

        create_result = result.get("createManualAccount", {})
        errors = create_result.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        account = create_result.get("account", {})
        return json.dumps({"success": True, "account": account}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create account: {e}")
        return f"Error creating account: {str(e)}"


@mcp.tool()
def update_account(
    account_id: str,
    name: Optional[str] = None,
    balance: Optional[float] = None,
    account_type: Optional[str] = None,
    account_subtype: Optional[str] = None,
    include_in_net_worth: Optional[bool] = None,
    hide_from_list: Optional[bool] = None,
    hide_transactions_from_reports: Optional[bool] = None,
    minimum_payment: Optional[float] = None,
    interest_rate: Optional[float] = None,
    apr: Optional[float] = None,
) -> str:
    """
    Update an existing account in Monarch Money.

    All parameters except account_id are optional — only provided fields
    are updated. Use get_accounts to find account IDs.

    Args:
        account_id: The ID of the account to update
        name: New display name for the account
        balance: New current balance
        account_type: Change account type (e.g. "loan", "credit", "depository")
        account_subtype: Change account subtype (e.g. "checking", "credit_card", "auto")
        include_in_net_worth: Whether to include in net worth calculation
        hide_from_list: Hide from the Accounts summary view
        hide_transactions_from_reports: Exclude from budgets and reports
        minimum_payment: Minimum payment due (for credit cards and loans)
        interest_rate: Annual interest rate as a percentage e.g. 5.9 (typically for loans)
        apr: Annual percentage rate as a percentage e.g. 25.7 (typically for credit cards)

    Returns:
        Updated account details.
    """
    try:
        from gql import gql

        async def _update_account():
            client = await get_monarch_client()

            account_input: Dict[str, Any] = {"id": str(account_id)}

            if name is not None:
                account_input["name"] = name
            if balance is not None:
                account_input["displayBalance"] = balance
            if account_type is not None:
                account_input["type"] = account_type
            if account_subtype is not None:
                account_input["subtype"] = account_subtype
            if include_in_net_worth is not None:
                account_input["includeInNetWorth"] = include_in_net_worth
            if hide_from_list is not None:
                account_input["hideFromList"] = hide_from_list
            if hide_transactions_from_reports is not None:
                account_input["hideTransactionsFromReports"] = (
                    hide_transactions_from_reports
                )
            if minimum_payment is not None:
                account_input["minimumPayment"] = minimum_payment
            if interest_rate is not None:
                account_input["interestRate"] = interest_rate
            if apr is not None:
                account_input["apr"] = apr

            query = gql(UPDATE_ACCOUNT_WITH_PAYMENT_FIELDS_MUTATION)
            return await client.gql_call(
                operation="Common_UpdateAccount",
                graphql_query=query,
                variables={"input": account_input},
            )

        result = run_async(_update_account())

        update_result = result.get("updateAccount", {})
        errors = update_result.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        account = update_result.get("account", {})
        return json.dumps({"success": True, "account": account}, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        return f"Error updating account: {str(e)}"


@mcp.tool()
def delete_account(account_id: str) -> str:
    """
    Delete an account from Monarch Money.

    WARNING: This permanently removes the account and all its transaction history.
    This action cannot be undone.

    Args:
        account_id: The ID of the account to delete (use get_accounts to find IDs)

    Returns:
        Confirmation of deletion with success boolean.
    """
    try:

        async def _delete_account():
            client = await get_monarch_client()
            return await client.delete_account(account_id=account_id)

        result = run_async(_delete_account())

        delete_result = result.get("deleteAccount", {})
        if delete_result.get("deleted"):
            return json.dumps(
                {
                    "success": True,
                    "message": f"Account {account_id} deleted successfully",
                },
                indent=2,
            )

        errors = delete_result.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        return json.dumps(
            {"success": False, "message": "Deletion failed for unknown reason"},
            indent=2,
        )
    except Exception as e:
        logger.error(f"Failed to delete account: {e}")
        return f"Error deleting account: {str(e)}"


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
