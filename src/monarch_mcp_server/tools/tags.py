"""Tag tools for the Monarch Money MCP Server."""

import json
import logging
from typing import List

from monarch_mcp_server.server import mcp, run_async, get_monarch_client

logger = logging.getLogger(__name__)


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
