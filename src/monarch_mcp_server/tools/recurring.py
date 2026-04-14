"""Recurring transaction and merchant tools for the Monarch Money MCP Server."""

import json
import logging
from datetime import datetime
from typing import Optional

from monarch_mcp_server.server import mcp, run_async, get_monarch_client
from monarch_mcp_server.queries import (
    GET_RECURRING_TRANSACTIONS_ENRICHED_QUERY,
    GET_MERCHANT_DETAILS_QUERY,
    UPDATE_MERCHANT_MUTATION,
)

logger = logging.getLogger(__name__)


@mcp.tool()
def get_recurring_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get upcoming recurring transactions.

    Returns scheduled recurring transactions with their merchants, amounts,
    accounts, and stream details. Each item represents a single occurrence
    of a recurring transaction within the date range.

    Stream fields include base_date (the configured billing/due date),
    review_status, and recurring_type (expense/income). Item fields include
    is_late, is_completed, and marked_paid_at for tracking payment status.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to start of current month)
        end_date: End date in YYYY-MM-DD format (defaults to end of current month)

    Returns:
        List of upcoming recurring transactions with account IDs, category IDs,
        and enriched stream details.
    """
    try:
        from gql import gql

        async def _get_recurring():
            client = await get_monarch_client()

            # Build date range
            if start_date and end_date:
                s_date, e_date = start_date, end_date
            elif not start_date and not end_date:
                now = datetime.now()
                s_date = now.strftime("%Y-%m-01")
                e_date = now.strftime("%Y-%m-28")
            else:
                # Library requires both or neither
                return await client.get_recurring_transactions(
                    start_date=start_date, end_date=end_date
                )

            # Try enriched custom query first
            try:
                query = gql(GET_RECURRING_TRANSACTIONS_ENRICHED_QUERY)
                result = await client.gql_call(
                    operation="Web_GetUpcomingRecurringTransactionItems",
                    graphql_query=query,
                    variables={
                        "startDate": s_date,
                        "endDate": e_date,
                        "filters": {},
                    },
                )
                return result, True
            except Exception as e:
                logger.warning(
                    f"Custom recurring query failed, falling back to library: {e}"
                )
                filters = {}
                if start_date:
                    filters["start_date"] = start_date
                if end_date:
                    filters["end_date"] = end_date
                result = await client.get_recurring_transactions(**filters)
                return result, False

        result, has_enriched_fields = run_async(_get_recurring())

        # Format recurring transactions
        recurring_list = []
        for item in result.get("recurringTransactionItems", []):
            stream = item.get("stream") or {}
            merchant = stream.get("merchant") or {}
            account = item.get("account") or {}
            category = item.get("category") or {}

            stream_info = {
                "id": stream.get("id"),
                "frequency": stream.get("frequency"),
                "amount": stream.get("amount"),
                "is_approximate": stream.get("isApproximate", False),
                "merchant": {
                    "id": merchant.get("id"),
                    "name": merchant.get("name"),
                }
                if merchant
                else None,
            }

            # Add enriched stream fields when available
            if has_enriched_fields:
                stream_info["is_active"] = stream.get("isActive")
                stream_info["name"] = stream.get("name")
                stream_info["logo_url"] = stream.get("logoUrl")
                stream_info["base_date"] = stream.get("baseDate")
                stream_info["review_status"] = stream.get("reviewStatus")
                stream_info["recurring_type"] = stream.get("recurringType")

            recurring_info = {
                "date": item.get("date"),
                "amount": item.get("amount"),
                "is_past": item.get("isPast", False),
                "transaction_id": item.get("transactionId"),
                "stream": stream_info if stream else None,
                "category": {
                    "id": category.get("id"),
                    "name": category.get("name"),
                }
                if category
                else None,
                "account": {
                    "id": account.get("id"),
                    "name": account.get("displayName"),
                }
                if account
                else None,
            }

            # Add enriched item fields when available
            if has_enriched_fields:
                recurring_info["amount_diff"] = item.get("amountDiff")
                recurring_info["is_late"] = item.get("isLate")
                recurring_info["is_completed"] = item.get("isCompleted")
                recurring_info["marked_paid_at"] = item.get("markedPaidAt")

            recurring_list.append(recurring_info)

        return json.dumps(recurring_list, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get recurring transactions: {e}")
        return f"Error getting recurring transactions: {str(e)}"


@mcp.tool()
def get_merchant_details(
    merchant_id: str,
) -> str:
    """
    Get merchant details including recurring transaction stream info.

    Returns merchant metadata (name, logo, transaction count, rule count)
    and its recurring transaction stream if one exists (frequency, amount,
    base_date, is_active).

    Use this before update_recurring_transaction to see current settings,
    or to look up a merchant's recurring stream ID.

    The merchant_id can be found in get_recurring_transactions output
    (stream.merchant.id) or in transaction details.

    Args:
        merchant_id: The merchant ID to look up.

    Returns:
        Merchant details with recurring stream information.
    """
    try:
        from gql import gql

        async def _get_merchant():
            client = await get_monarch_client()
            query = gql(GET_MERCHANT_DETAILS_QUERY)
            return await client.gql_call(
                operation="Common_GetEditMerchant",
                graphql_query=query,
                variables={"merchantId": merchant_id},
            )

        result = run_async(_get_merchant())

        merchant = result.get("merchant")
        if not merchant:
            return json.dumps(
                {"success": False, "message": f"Merchant {merchant_id} not found"},
                indent=2,
            )

        stream = merchant.get("recurringTransactionStream")
        merchant_info = {
            "id": merchant.get("id"),
            "name": merchant.get("name"),
            "logo_url": merchant.get("logoUrl"),
            "transaction_count": merchant.get("transactionCount"),
            "rule_count": merchant.get("ruleCount"),
            "can_be_deleted": merchant.get("canBeDeleted"),
            "has_active_recurring_streams": merchant.get("hasActiveRecurringStreams"),
            "recurring_stream": {
                "id": stream.get("id"),
                "frequency": stream.get("frequency"),
                "amount": stream.get("amount"),
                "base_date": stream.get("baseDate"),
                "is_active": stream.get("isActive"),
            }
            if stream
            else None,
        }

        return json.dumps(merchant_info, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get merchant details: {e}")
        return f"Error getting merchant details: {str(e)}"


@mcp.tool()
def update_recurring_transaction(
    merchant_id: str,
    name: Optional[str] = None,
    frequency: Optional[str] = None,
    base_date: Optional[str] = None,
    amount: Optional[float] = None,
    is_active: Optional[bool] = None,
) -> str:
    """
    Update a recurring transaction's settings via its merchant.

    In Monarch Money, recurring transactions are managed through merchants.
    This tool fetches the merchant's current recurring stream settings and
    merges your changes, so you only need to provide the fields you want
    to change.

    The base_date controls the billing/due day — the day-of-month from
    base_date determines when the recurring transaction is expected each
    period (e.g., "2024-01-15" means the 15th of each month).

    Args:
        merchant_id: The merchant ID (from get_recurring_transactions stream.merchant.id
                     or get_merchant_details)
        name: New merchant name (optional)
        frequency: Recurrence frequency — "monthly", "biweekly", "bimonthly",
                   "semimonthly_mid_end", etc. (optional)
        base_date: Base date in YYYY-MM-DD format — the day-of-month sets the
                   billing/due day (optional)
        amount: Expected amount per occurrence — negative for expenses,
                positive for income (optional)
        is_active: Whether the recurring stream is active (optional, set False to
                   disable without deleting)

    Returns:
        Updated merchant and recurring stream details.

    Example:
        Change due day to the 15th:
        update_recurring_transaction(merchant_id="12345", base_date="2024-01-15")

        Disable a recurring transaction:
        update_recurring_transaction(merchant_id="12345", is_active=False)
    """
    try:
        from gql import gql

        async def _update_recurring():
            client = await get_monarch_client()

            # Step 1: Fetch current merchant state for merge
            query = gql(GET_MERCHANT_DETAILS_QUERY)
            current = await client.gql_call(
                operation="Common_GetEditMerchant",
                graphql_query=query,
                variables={"merchantId": merchant_id},
            )

            merchant = current.get("merchant")
            if not merchant:
                return {
                    "success": False,
                    "message": f"Merchant {merchant_id} not found",
                }

            stream = merchant.get("recurringTransactionStream")
            if not stream:
                return {
                    "success": False,
                    "message": (
                        f"Merchant '{merchant.get('name')}' has no recurring "
                        f"transaction stream. Recurring streams are created "
                        f"automatically by Monarch when it detects recurring "
                        f"patterns, or can be set up in the Monarch web app."
                    ),
                }

            # Step 2: Merge user-provided fields with current values
            merged_name = name if name is not None else merchant.get("name")
            merged_recurrence = {
                "isRecurring": True,
                "frequency": frequency
                if frequency is not None
                else stream.get("frequency"),
                "baseDate": base_date
                if base_date is not None
                else stream.get("baseDate"),
                "amount": amount if amount is not None else stream.get("amount"),
                "isActive": is_active
                if is_active is not None
                else stream.get("isActive"),
            }

            # Step 3: Execute mutation
            mutation = gql(UPDATE_MERCHANT_MUTATION)
            result = await client.gql_call(
                operation="Common_UpdateMerchant",
                graphql_query=mutation,
                variables={
                    "input": {
                        "merchantId": merchant_id,
                        "name": merged_name,
                        "recurrence": merged_recurrence,
                    }
                },
            )

            return result

        result = run_async(_update_recurring())

        # Handle pre-mutation errors (merchant not found, no stream)
        if isinstance(result, dict) and "success" in result:
            return json.dumps(result, indent=2)

        # Check for API errors
        update_data = result.get("updateMerchant", {})
        errors = update_data.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        # Format success response
        merchant = update_data.get("merchant", {})
        stream = merchant.get("recurringTransactionStream") or {}
        return json.dumps(
            {
                "success": True,
                "message": f"Recurring transaction updated for '{merchant.get('name')}'",
                "merchant": {
                    "id": merchant.get("id"),
                    "name": merchant.get("name"),
                },
                "recurring_stream": {
                    "id": stream.get("id"),
                    "frequency": stream.get("frequency"),
                    "amount": stream.get("amount"),
                    "base_date": stream.get("baseDate"),
                    "is_active": stream.get("isActive"),
                },
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        logger.error(f"Failed to update recurring transaction: {e}")
        return f"Error updating recurring transaction: {str(e)}"


@mcp.tool()
def disable_recurring_transaction(
    merchant_id: str,
) -> str:
    """
    Disable a recurring transaction stream without deleting it.

    This is a convenience tool that sets is_active=False on the merchant's
    recurring stream. All other settings (frequency, amount, base_date)
    are preserved. The stream can be re-enabled later by calling
    update_recurring_transaction with is_active=True.

    Args:
        merchant_id: The merchant ID whose recurring stream to disable
                     (from get_recurring_transactions stream.merchant.id)

    Returns:
        Confirmation with the disabled stream details.
    """
    try:
        from gql import gql

        async def _disable():
            client = await get_monarch_client()

            # Fetch current state
            query = gql(GET_MERCHANT_DETAILS_QUERY)
            current = await client.gql_call(
                operation="Common_GetEditMerchant",
                graphql_query=query,
                variables={"merchantId": merchant_id},
            )

            merchant = current.get("merchant")
            if not merchant:
                return {
                    "success": False,
                    "message": f"Merchant {merchant_id} not found",
                }

            stream = merchant.get("recurringTransactionStream")
            if not stream:
                return {
                    "success": False,
                    "message": (
                        f"Merchant '{merchant.get('name')}' has no recurring "
                        f"transaction stream to disable."
                    ),
                }

            if not stream.get("isActive"):
                return {
                    "success": True,
                    "message": (
                        f"Recurring stream for '{merchant.get('name')}' "
                        f"is already inactive."
                    ),
                }

            # Set isActive=False, preserve everything else
            mutation = gql(UPDATE_MERCHANT_MUTATION)
            result = await client.gql_call(
                operation="Common_UpdateMerchant",
                graphql_query=mutation,
                variables={
                    "input": {
                        "merchantId": merchant_id,
                        "name": merchant.get("name"),
                        "recurrence": {
                            "isRecurring": True,
                            "frequency": stream.get("frequency"),
                            "baseDate": stream.get("baseDate"),
                            "amount": stream.get("amount"),
                            "isActive": False,
                        },
                    }
                },
            )

            return result

        result = run_async(_disable())

        # Handle pre-mutation results
        if isinstance(result, dict) and "success" in result:
            return json.dumps(result, indent=2)

        # Check for API errors
        update_data = result.get("updateMerchant", {})
        errors = update_data.get("errors")
        if errors:
            return json.dumps({"success": False, "errors": errors}, indent=2)

        # Format success response
        merchant = update_data.get("merchant", {})
        stream = merchant.get("recurringTransactionStream") or {}
        return json.dumps(
            {
                "success": True,
                "message": f"Recurring stream disabled for '{merchant.get('name')}'",
                "merchant": {
                    "id": merchant.get("id"),
                    "name": merchant.get("name"),
                },
                "recurring_stream": {
                    "id": stream.get("id"),
                    "frequency": stream.get("frequency"),
                    "amount": stream.get("amount"),
                    "base_date": stream.get("baseDate"),
                    "is_active": stream.get("isActive"),
                },
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        logger.error(f"Failed to disable recurring transaction: {e}")
        return f"Error disabling recurring transaction: {str(e)}"
