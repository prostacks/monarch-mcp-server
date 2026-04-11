"""Tests for get_accounts MCP tool with enriched fields and payment details."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Mock the monarchmoney module before importing server
import sys

sys.modules["monarchmoney"] = MagicMock()
sys.modules["monarchmoney"].MonarchMoney = MagicMock
sys.modules["monarchmoney"].MonarchMoneyEndpoints = MagicMock()
sys.modules["monarchmoney"].RequireMFAException = type(
    "RequireMFAException", (Exception,), {}
)

from monarch_mcp_server.server import get_accounts


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_account(
    id="acc_1",
    display_name="Test Account",
    type_name="depository",
    type_display="Depository",
    type_group="ASSET",
    subtype_name="checking",
    subtype_display="Checking",
    current_balance=1000.0,
    display_balance=1000.0,
    institution_name="Chase",
    institution_url="https://chase.com",
    deactivated_at=None,
    is_asset=True,
    is_manual=False,
    include_in_net_worth=True,
    mask="1234",
    logo_url="https://logo.com/chase.png",
    data_provider="plaid",
    display_last_updated_at="2026-04-10T12:00:00Z",
    minimum_payment=None,
    apr=None,
    interest_rate=None,
    limit=None,
    **extra,
):
    """Build a mock account dict matching the custom GraphQL query shape."""
    return {
        "id": id,
        "displayName": display_name,
        "syncDisabled": False,
        "deactivatedAt": deactivated_at,
        "isHidden": False,
        "isAsset": is_asset,
        "mask": mask,
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2026-04-10T12:00:00Z",
        "displayLastUpdatedAt": display_last_updated_at,
        "currentBalance": current_balance,
        "displayBalance": display_balance,
        "includeInNetWorth": include_in_net_worth,
        "hideFromList": False,
        "hideTransactionsFromReports": False,
        "dataProvider": data_provider,
        "dataProviderAccountId": "ext_123",
        "isManual": is_manual,
        "transactionsCount": 42,
        "holdingsCount": 0,
        "order": 0,
        "logoUrl": logo_url,
        "type": {
            "name": type_name,
            "display": type_display,
            "group": type_group,
            "__typename": "AccountType",
        },
        "subtype": {
            "name": subtype_name,
            "display": subtype_display,
            "__typename": "AccountSubtype",
        }
        if subtype_name
        else None,
        "credential": {
            "id": "cred_1",
            "updateRequired": False,
            "disconnectedFromDataProviderAt": None,
            "dataProvider": data_provider,
            "institution": {
                "id": "inst_1",
                "name": institution_name,
                "status": "OK",
                "__typename": "Institution",
            },
            "__typename": "Credential",
        }
        if institution_name
        else None,
        "institution": {
            "id": "inst_1",
            "name": institution_name,
            "primaryColor": "#003DA5",
            "url": institution_url,
            "__typename": "Institution",
        }
        if institution_name
        else None,
        "minimumPayment": minimum_payment,
        "interestRate": interest_rate,
        "apr": apr,
        "limit": limit,
        "__typename": "Account",
        **extra,
    }


def _make_credit_card(**overrides):
    """Build a mock credit card account with typical payment fields."""
    defaults = dict(
        id="acc_cc",
        display_name="Chase Sapphire",
        type_name="credit",
        type_display="Credit Card",
        type_group="LIABILITY",
        subtype_name="credit_card",
        subtype_display="Credit Card",
        current_balance=-2500.0,
        display_balance=2500.0,
        is_asset=False,
        minimum_payment=75.0,
        apr=25.7,
        interest_rate=None,
        limit=10000.0,
    )
    defaults.update(overrides)
    return _make_account(**defaults)


def _make_loan(**overrides):
    """Build a mock loan account with typical payment fields."""
    defaults = dict(
        id="acc_loan",
        display_name="Best Egg Personal Loan",
        type_name="loan",
        type_display="Loan",
        type_group="LIABILITY",
        subtype_name="personal",
        subtype_display="Personal Loan",
        current_balance=-18521.50,
        display_balance=18521.50,
        is_asset=False,
        minimum_payment=520.0,
        apr=None,
        interest_rate=5.9,
        limit=None,
    )
    defaults.update(overrides)
    return _make_account(**defaults)


def _make_checking(**overrides):
    """Build a mock checking account (no payment fields)."""
    defaults = dict(
        id="acc_chk",
        display_name="Main Checking",
        type_name="depository",
        type_display="Depository",
        type_group="ASSET",
        subtype_name="checking",
        subtype_display="Checking",
        current_balance=1500.0,
        display_balance=1500.0,
        is_asset=True,
        minimum_payment=None,
        apr=None,
        interest_rate=None,
        limit=None,
    )
    defaults.update(overrides)
    return _make_account(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetAccountsEnrichedFields:
    """Tests for the enriched fields in get_accounts output."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_get_accounts_enriched_fields(self, mock_get_client):
        """Enriched response includes all new fields (subtype, is_asset, logo_url, etc.)."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [_make_checking()]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        acct = accounts[0]

        # Original fields still present
        assert acct["id"] == "acc_chk"
        assert acct["name"] == "Main Checking"
        assert acct["type"] == "depository"
        assert acct["balance"] == 1500.0
        assert acct["institution"] == "Chase"
        assert acct["is_active"] is True

        # New enriched fields
        assert acct["type_display"] == "Depository"
        assert acct["type_group"] == "ASSET"
        assert acct["subtype"] == "checking"
        assert acct["subtype_display"] == "Checking"
        assert acct["display_balance"] == 1500.0
        assert acct["is_asset"] is True
        assert acct["is_manual"] is False
        assert acct["include_in_net_worth"] is True
        assert acct["mask"] == "1234"
        assert acct["logo_url"] == "https://logo.com/chase.png"
        assert acct["data_provider"] == "plaid"
        assert acct["last_updated"] == "2026-04-10T12:00:00Z"
        assert acct["institution_url"] == "https://chase.com"

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_get_accounts_handles_missing_optional_fields(self, mock_get_client):
        """Graceful handling when optional fields are None or missing."""
        account = _make_account(
            institution_name=None,
            institution_url=None,
            subtype_name=None,
            logo_url=None,
            mask=None,
            data_provider=None,
        )
        # Also clear credential since institution_name=None skips it
        account["credential"] = None

        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [account]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        acct = accounts[0]
        assert acct["institution"] is None
        assert acct["institution_url"] is None
        assert acct["subtype"] is None
        assert acct["subtype_display"] is None
        assert acct["logo_url"] is None
        assert acct["mask"] is None
        assert acct["data_provider"] is None


class TestGetAccountsPaymentDetails:
    """Tests for payment_details on credit/loan accounts."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_credit_card_payment_details(self, mock_get_client):
        """Credit card accounts include payment_details with minimum_payment, apr, credit_limit."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [_make_credit_card()]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        acct = accounts[0]
        assert "payment_details" in acct

        pd = acct["payment_details"]
        assert pd["minimum_payment"] == 75.0
        assert pd["apr"] == 25.7
        assert pd["credit_limit"] == 10000.0
        # interest_rate is None for credit cards, so should NOT be in payment_details
        assert "interest_rate" not in pd

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_loan_payment_details(self, mock_get_client):
        """Loan accounts include payment_details with minimum_payment and interest_rate."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [_make_loan()]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        acct = accounts[0]
        assert "payment_details" in acct

        pd = acct["payment_details"]
        assert pd["minimum_payment"] == 520.0
        assert pd["interest_rate"] == 5.9
        # apr and limit are None for loans, so should NOT be in payment_details
        assert "apr" not in pd
        assert "credit_limit" not in pd

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_depository_no_payment_details(self, mock_get_client):
        """Depository accounts (checking/savings) do NOT get a payment_details key."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [_make_checking()]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        assert "payment_details" not in accounts[0]

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_mixed_account_types(self, mock_get_client):
        """Mixed response: depository, credit, and loan accounts handled correctly."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "accounts": [
                _make_checking(),
                _make_credit_card(),
                _make_loan(),
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 3

        # Checking — no payment_details
        checking = accounts[0]
        assert checking["name"] == "Main Checking"
        assert "payment_details" not in checking

        # Credit card — has payment_details with apr, credit_limit, minimum_payment
        credit = accounts[1]
        assert credit["name"] == "Chase Sapphire"
        assert "payment_details" in credit
        assert credit["payment_details"]["apr"] == 25.7
        assert credit["payment_details"]["credit_limit"] == 10000.0
        assert credit["payment_details"]["minimum_payment"] == 75.0

        # Loan — has payment_details with interest_rate, minimum_payment
        loan = accounts[2]
        assert loan["name"] == "Best Egg Personal Loan"
        assert "payment_details" in loan
        assert loan["payment_details"]["interest_rate"] == 5.9
        assert loan["payment_details"]["minimum_payment"] == 520.0


class TestGetAccountsFallback:
    """Tests for fallback behavior when custom query fails."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_fallback_to_library_on_custom_query_failure(self, mock_get_client):
        """If custom GraphQL query fails, falls back to library's get_accounts()."""
        mock_client = AsyncMock()
        # Custom gql_call fails
        mock_client.gql_call.side_effect = Exception("Unknown field 'minimumPayment'")
        # Library fallback succeeds (returns standard library shape)
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "acc_1",
                    "displayName": "Main Checking",
                    "type": {
                        "name": "depository",
                        "display": "Depository",
                        "group": "ASSET",
                    },
                    "subtype": {"name": "checking", "display": "Checking"},
                    "currentBalance": 1500.0,
                    "displayBalance": 1500.0,
                    "isAsset": True,
                    "isManual": False,
                    "includeInNetWorth": True,
                    "mask": "1234",
                    "logoUrl": "https://logo.com/chase.png",
                    "displayLastUpdatedAt": "2026-04-10T12:00:00Z",
                    "dataProvider": "plaid",
                    "deactivatedAt": None,
                    "institution": {"name": "Chase", "url": "https://chase.com"},
                    "credential": {"dataProvider": "plaid"},
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        acct = accounts[0]
        # Basic enriched fields still work from library fallback
        assert acct["id"] == "acc_1"
        assert acct["name"] == "Main Checking"
        assert acct["type"] == "depository"
        assert acct["balance"] == 1500.0
        assert acct["institution"] == "Chase"
        assert acct["is_asset"] is True
        assert acct["subtype"] == "checking"
        assert acct["logo_url"] == "https://logo.com/chase.png"
        # No payment_details since fallback doesn't have payment fields
        assert "payment_details" not in acct

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_empty_accounts_list(self, mock_get_client):
        """Edge case: API returns zero accounts."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": []}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert accounts == []

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_error_handling_both_paths_fail(self, mock_get_client):
        """If both custom query and library fallback fail, returns error message."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = Exception("GraphQL error")
        mock_client.get_accounts.side_effect = Exception("Network timeout")
        mock_get_client.return_value = mock_client

        result = get_accounts()

        assert result.startswith("Error getting accounts:")
        assert "Network timeout" in result
