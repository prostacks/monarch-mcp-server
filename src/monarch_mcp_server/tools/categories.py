"""Category tools for the Monarch Money MCP Server."""

import json
import logging

from monarch_mcp_server.server import mcp, run_async, get_monarch_client

logger = logging.getLogger(__name__)


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
