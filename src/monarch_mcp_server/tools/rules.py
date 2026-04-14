"""Transaction rule tools for the Monarch Money MCP Server."""

import json
import logging
from typing import Any, Dict, List, Optional

from monarch_mcp_server.server import mcp, run_async, get_monarch_client
from monarch_mcp_server.queries import (
    GET_TRANSACTION_RULES_QUERY,
    CREATE_TRANSACTION_RULE_MUTATION,
    UPDATE_TRANSACTION_RULE_MUTATION,
    DELETE_TRANSACTION_RULE_MUTATION,
)

logger = logging.getLogger(__name__)


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
        Create rule: "Amazon purchases -> Shopping category"
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
