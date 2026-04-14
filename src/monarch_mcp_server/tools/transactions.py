"""Transaction tools for the Monarch Money MCP Server."""

import json
import logging
from typing import List, Optional

from monarch_mcp_server.server import mcp, run_async, get_monarch_client

logger = logging.getLogger(__name__)


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
                "merchant_id": txn.get("merchant", {}).get("id")
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
    merchant_name: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
    notes: Optional[str] = None,
    review_status: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Supports updating multiple fields in a single call. All parameters
    except transaction_id are optional — only provided fields are updated.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        merchant_name: New merchant/payee name (corrects data provider names)
        category_id: New category ID (use get_categories for valid IDs)
        date: New transaction date in YYYY-MM-DD format
        notes: Notes to attach to the transaction
        review_status: Set to "reviewed" or "needs_review"
        hide_from_reports: True to hide from budgets/reports, False to include
    """
    try:

        async def _update_transaction():
            client = await get_monarch_client()

            update_data = {"transaction_id": transaction_id}

            if amount is not None:
                update_data["amount"] = amount
            if merchant_name is not None:
                update_data["merchant_name"] = merchant_name
            if category_id is not None:
                update_data["category_id"] = category_id
            if date is not None:
                update_data["date"] = date
            if notes is not None:
                update_data["notes"] = notes
            if review_status == "reviewed":
                update_data["needs_review"] = False
            elif review_status == "needs_review":
                update_data["needs_review"] = True
            if hide_from_reports is not None:
                update_data["hide_from_reports"] = hide_from_reports

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
                "merchant_id": txn.get("merchant", {}).get("id")
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
                "merchant_id": txn.get("merchant", {}).get("id")
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
