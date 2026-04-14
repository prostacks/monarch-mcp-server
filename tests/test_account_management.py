"""Tests for account management MCP tools (Issue #2): create_account, update_account, delete_account."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from monarch_mcp_server.tools.accounts import (
    create_account,
    update_account,
    delete_account,
)


# ---------------------------------------------------------------------------
# TestCreateAccount
# ---------------------------------------------------------------------------


class TestCreateAccount:
    """Tests for create_account tool."""

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_create_minimal(self, mock_get_client):
        """Create with only required params passes correct args to library."""
        mock_client = AsyncMock()
        mock_client.create_manual_account.return_value = {
            "createManualAccount": {
                "account": {
                    "id": "acc_new",
                    "displayName": "Test Loan",
                    "currentBalance": 0.0,
                    "isManual": True,
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = create_account(
            name="Test Loan",
            account_type="loan",
            account_subtype="personal",
        )

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["account"]["id"] == "acc_new"
        assert parsed["account"]["displayName"] == "Test Loan"

        # Verify library call args
        call_kwargs = mock_client.create_manual_account.call_args.kwargs
        assert call_kwargs["account_name"] == "Test Loan"
        assert call_kwargs["account_type"] == "loan"
        assert call_kwargs["account_sub_type"] == "personal"
        assert call_kwargs["account_balance"] == 0.0
        assert call_kwargs["is_in_net_worth"] is True

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_create_all_fields(self, mock_get_client):
        """Create with all optional params passes them through."""
        mock_client = AsyncMock()
        mock_client.create_manual_account.return_value = {
            "createManualAccount": {
                "account": {
                    "id": "acc_new",
                    "displayName": "Savings",
                    "currentBalance": 500.0,
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = create_account(
            name="Savings",
            account_type="depository",
            account_subtype="savings",
            balance=500.0,
            include_in_net_worth=False,
        )

        parsed = json.loads(result)
        assert parsed["success"] is True

        call_kwargs = mock_client.create_manual_account.call_args.kwargs
        assert call_kwargs["account_balance"] == 500.0
        assert call_kwargs["is_in_net_worth"] is False

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_create_negative_balance(self, mock_get_client):
        """Negative balance (debt) passes through correctly."""
        mock_client = AsyncMock()
        mock_client.create_manual_account.return_value = {
            "createManualAccount": {
                "account": {
                    "id": "acc_new",
                    "displayName": "Credit Card",
                    "currentBalance": -2500.0,
                },
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        create_account(
            name="Credit Card",
            account_type="credit",
            account_subtype="credit_card",
            balance=-2500.0,
        )

        call_kwargs = mock_client.create_manual_account.call_args.kwargs
        assert call_kwargs["account_balance"] == -2500.0

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_create_api_errors(self, mock_get_client):
        """API-level errors return success=False with error details."""
        mock_client = AsyncMock()
        mock_client.create_manual_account.return_value = {
            "createManualAccount": {
                "account": None,
                "errors": {
                    "message": "Invalid account type",
                    "code": "INVALID_INPUT",
                    "fieldErrors": [
                        {"field": "type", "messages": ["Not a valid type"]}
                    ],
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = create_account(
            name="Bad Account",
            account_type="invalid",
            account_subtype="nope",
        )

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "errors" in parsed

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_create_exception(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Network timeout")

        result = create_account(
            name="Test",
            account_type="loan",
            account_subtype="personal",
        )

        assert "Error creating account:" in result
        assert "Network timeout" in result


# ---------------------------------------------------------------------------
# TestUpdateAccount
# ---------------------------------------------------------------------------


class TestUpdateAccount:
    """Tests for update_account tool."""

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_name_only(self, mock_get_client):
        """Update with only name passes id + name in input."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "displayName": "Renamed Account"},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = update_account(account_id="acc_1", name="Renamed Account")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["account"]["displayName"] == "Renamed Account"

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["id"] == "acc_1"
        assert account_input["name"] == "Renamed Account"
        # Only id + name should be present
        assert "displayBalance" not in account_input
        assert "minimumPayment" not in account_input

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_balance(self, mock_get_client):
        """Update balance passes displayBalance in input."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "currentBalance": 5000.0},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", balance=5000.0)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["displayBalance"] == 5000.0

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_include_in_net_worth_true(self, mock_get_client):
        """include_in_net_worth=True is forwarded."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "includeInNetWorth": True},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", include_in_net_worth=True)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["includeInNetWorth"] is True

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_include_in_net_worth_false(self, mock_get_client):
        """include_in_net_worth=False is forwarded (not dropped by truthiness)."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "includeInNetWorth": False},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", include_in_net_worth=False)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["includeInNetWorth"] is False

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_minimum_payment(self, mock_get_client):
        """minimum_payment maps to minimumPayment in input."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "minimumPayment": 75.0},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", minimum_payment=75.0)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["minimumPayment"] == 75.0

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_interest_rate(self, mock_get_client):
        """interest_rate maps to interestRate in input."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "interestRate": 5.9},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", interest_rate=5.9)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["interestRate"] == 5.9

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_apr(self, mock_get_client):
        """apr maps to apr in input."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1", "apr": 25.7},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(account_id="acc_1", apr=25.7)

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["apr"] == 25.7

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_all_fields(self, mock_get_client):
        """All fields present in input when all params provided."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": {"id": "acc_1"},
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        update_account(
            account_id="acc_1",
            name="Updated Name",
            balance=1000.0,
            account_type="credit",
            account_subtype="credit_card",
            include_in_net_worth=True,
            hide_from_list=False,
            hide_transactions_from_reports=True,
            minimum_payment=50.0,
            interest_rate=None,  # explicitly None should NOT be in input
            apr=28.9,
        )

        call_kwargs = mock_client.gql_call.call_args.kwargs
        account_input = call_kwargs["variables"]["input"]
        assert account_input["id"] == "acc_1"
        assert account_input["name"] == "Updated Name"
        assert account_input["displayBalance"] == 1000.0
        assert account_input["type"] == "credit"
        assert account_input["subtype"] == "credit_card"
        assert account_input["includeInNetWorth"] is True
        assert account_input["hideFromList"] is False
        assert account_input["hideTransactionsFromReports"] is True
        assert account_input["minimumPayment"] == 50.0
        assert account_input["apr"] == 28.9
        # interest_rate was None, should not appear
        assert "interestRate" not in account_input

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_api_errors(self, mock_get_client):
        """API-level errors return success=False."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "updateAccount": {
                "account": None,
                "errors": {"message": "Account not found", "code": "NOT_FOUND"},
            }
        }
        mock_get_client.return_value = mock_client

        result = update_account(account_id="acc_bad", name="Nope")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "errors" in parsed

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_update_exception(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Connection refused")

        result = update_account(account_id="acc_1", balance=100.0)

        assert "Error updating account:" in result
        assert "Connection refused" in result


# ---------------------------------------------------------------------------
# TestDeleteAccount
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    """Tests for delete_account tool."""

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_delete_success(self, mock_get_client):
        """Successful deletion returns success=True."""
        mock_client = AsyncMock()
        mock_client.delete_account.return_value = {
            "deleteAccount": {
                "deleted": True,
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = delete_account(account_id="acc_1")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "acc_1" in parsed["message"]

        mock_client.delete_account.assert_called_once_with(account_id="acc_1")

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_delete_api_error(self, mock_get_client):
        """API errors return success=False with error details."""
        mock_client = AsyncMock()
        mock_client.delete_account.return_value = {
            "deleteAccount": {
                "deleted": False,
                "errors": {
                    "message": "Cannot delete synced account",
                    "code": "FORBIDDEN",
                },
            }
        }
        mock_get_client.return_value = mock_client

        result = delete_account(account_id="acc_synced")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "errors" in parsed

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_delete_unknown_failure(self, mock_get_client):
        """Empty/unexpected response returns success=False with unknown error."""
        mock_client = AsyncMock()
        mock_client.delete_account.return_value = {
            "deleteAccount": {
                "deleted": False,
                "errors": None,
            }
        }
        mock_get_client.return_value = mock_client

        result = delete_account(account_id="acc_1")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "unknown" in parsed["message"].lower()

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_delete_exception(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Server error")

        result = delete_account(account_id="acc_1")

        assert "Error deleting account:" in result
        assert "Server error" in result
