"""Tests for merchant & recurring transaction management tools:
get_merchant_details, update_recurring_transaction, disable_recurring_transaction."""

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

from monarch_mcp_server.server import (
    get_merchant_details,
    update_recurring_transaction,
    disable_recurring_transaction,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


# Sentinel to distinguish "use default stream" from "no stream"
_UNSET = object()


def _make_merchant(
    id="merch_1",
    name="Netflix",
    logo_url="https://example.com/netflix.png",
    transaction_count=24,
    rule_count=1,
    can_be_deleted=False,
    has_active_recurring_streams=True,
    stream=_UNSET,
):
    """Build a mock merchant response from Common_GetEditMerchant.

    Pass stream=None explicitly to create a merchant with no recurring stream.
    Omit stream (or pass _UNSET) to use a default monthly stream.
    """
    if stream is _UNSET:
        stream = {
            "id": "stream_1",
            "frequency": "monthly",
            "amount": -15.99,
            "baseDate": "2024-03-18",
            "isActive": True,
            "__typename": "RecurringTransactionStream",
        }
    return {
        "merchant": {
            "id": id,
            "name": name,
            "logoUrl": logo_url,
            "transactionCount": transaction_count,
            "ruleCount": rule_count,
            "canBeDeleted": can_be_deleted,
            "hasActiveRecurringStreams": has_active_recurring_streams,
            "recurringTransactionStream": stream,
            "__typename": "Merchant",
        }
    }


def _make_update_response(
    id="merch_1",
    name="Netflix",
    stream_id="stream_1",
    frequency="monthly",
    amount=-15.99,
    base_date="2024-03-18",
    is_active=True,
    errors=None,
):
    """Build a mock response from Common_UpdateMerchant."""
    return {
        "updateMerchant": {
            "merchant": {
                "id": id,
                "name": name,
                "recurringTransactionStream": {
                    "id": stream_id,
                    "frequency": frequency,
                    "amount": amount,
                    "baseDate": base_date,
                    "isActive": is_active,
                    "__typename": "RecurringTransactionStream",
                },
                "__typename": "Merchant",
            },
            "errors": errors,
            "__typename": "UpdateMerchantMutation",
        }
    }


# ---------------------------------------------------------------------------
# TestGetMerchantDetails
# ---------------------------------------------------------------------------


class TestGetMerchantDetails:
    """Tests for get_merchant_details tool."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_success_with_stream(self, mock_get_client):
        """Returns merchant info and recurring stream details."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant()
        mock_get_client.return_value = mock_client

        result = get_merchant_details(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["id"] == "merch_1"
        assert parsed["name"] == "Netflix"
        assert parsed["logo_url"] == "https://example.com/netflix.png"
        assert parsed["transaction_count"] == 24
        assert parsed["rule_count"] == 1
        assert parsed["can_be_deleted"] is False
        assert parsed["has_active_recurring_streams"] is True

        stream = parsed["recurring_stream"]
        assert stream["id"] == "stream_1"
        assert stream["frequency"] == "monthly"
        assert stream["amount"] == -15.99
        assert stream["base_date"] == "2024-03-18"
        assert stream["is_active"] is True

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_merchant_without_stream(self, mock_get_client):
        """Merchant with no recurring stream returns null for recurring_stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(
            stream=None, has_active_recurring_streams=False
        )
        mock_get_client.return_value = mock_client

        result = get_merchant_details(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["name"] == "Netflix"
        assert parsed["recurring_stream"] is None
        assert parsed["has_active_recurring_streams"] is False

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_merchant_not_found(self, mock_get_client):
        """Returns error when merchant doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = get_merchant_details(merchant_id="bad_id")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "not found" in parsed["message"]

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_exception_handling(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Network error")

        result = get_merchant_details(merchant_id="merch_1")

        assert "Error getting merchant details:" in result
        assert "Network error" in result


# ---------------------------------------------------------------------------
# TestUpdateRecurringTransaction
# ---------------------------------------------------------------------------


class TestUpdateRecurringTransaction:
    """Tests for update_recurring_transaction tool."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_update_base_date_only(self, mock_get_client):
        """Partial update: only change base_date, other fields preserved."""
        mock_client = AsyncMock()
        # First call: fetch current state; second call: mutation
        mock_client.gql_call.side_effect = [
            _make_merchant(),  # GET current state
            _make_update_response(base_date="2024-01-15"),  # UPDATE result
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1", base_date="2024-01-15"
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["recurring_stream"]["base_date"] == "2024-01-15"

        # Verify the mutation was called with merged values
        mutation_call = mock_client.gql_call.call_args_list[1]
        variables = mutation_call.kwargs["variables"]
        recurrence = variables["input"]["recurrence"]
        assert recurrence["baseDate"] == "2024-01-15"  # changed
        assert recurrence["frequency"] == "monthly"  # preserved
        assert recurrence["amount"] == -15.99  # preserved
        assert recurrence["isActive"] is True  # preserved

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_update_is_active(self, mock_get_client):
        """Update is_active flag."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(),
            _make_update_response(is_active=False),
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(merchant_id="merch_1", is_active=False)
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["recurring_stream"]["is_active"] is False

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_update_all_fields(self, mock_get_client):
        """Update all fields at once."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(),
            _make_update_response(
                name="Netflix Premium",
                frequency="bimonthly",
                amount=-22.99,
                base_date="2024-02-01",
                is_active=True,
            ),
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1",
            name="Netflix Premium",
            frequency="bimonthly",
            base_date="2024-02-01",
            amount=-22.99,
            is_active=True,
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["merchant"]["name"] == "Netflix Premium"
        assert parsed["recurring_stream"]["frequency"] == "bimonthly"
        assert parsed["recurring_stream"]["amount"] == -22.99
        assert parsed["recurring_stream"]["base_date"] == "2024-02-01"

        # Verify all fields in mutation input
        mutation_call = mock_client.gql_call.call_args_list[1]
        variables = mutation_call.kwargs["variables"]
        assert variables["input"]["name"] == "Netflix Premium"
        recurrence = variables["input"]["recurrence"]
        assert recurrence["frequency"] == "bimonthly"
        assert recurrence["baseDate"] == "2024-02-01"
        assert recurrence["amount"] == -22.99
        assert recurrence["isActive"] is True

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_merchant_not_found(self, mock_get_client):
        """Returns error when merchant doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="bad_id", base_date="2024-01-15"
        )
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "not found" in parsed["message"]

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_merchant_no_recurring_stream(self, mock_get_client):
        """Returns error when merchant has no recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(stream=None)
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(merchant_id="merch_1", is_active=False)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "no recurring" in parsed["message"].lower()

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_api_errors_returned(self, mock_get_client):
        """API-level errors from mutation are returned."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(),
            {
                "updateMerchant": {
                    "merchant": None,
                    "errors": {
                        "message": "Invalid frequency",
                        "code": "INVALID_INPUT",
                    },
                }
            },
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1", frequency="invalid"
        )
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "errors" in parsed

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_exception_handling(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Connection refused")

        result = update_recurring_transaction(
            merchant_id="merch_1", base_date="2024-01-15"
        )

        assert "Error updating recurring transaction:" in result
        assert "Connection refused" in result


# ---------------------------------------------------------------------------
# TestDisableRecurringTransaction
# ---------------------------------------------------------------------------


class TestDisableRecurringTransaction:
    """Tests for disable_recurring_transaction tool."""

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_disable_active_stream(self, mock_get_client):
        """Successfully disables an active recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(),  # GET: stream is active
            _make_update_response(is_active=False),  # UPDATE: now inactive
        ]
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "disabled" in parsed["message"].lower()
        assert parsed["recurring_stream"]["is_active"] is False

        # Verify mutation sets isActive=False
        mutation_call = mock_client.gql_call.call_args_list[1]
        variables = mutation_call.kwargs["variables"]
        assert variables["input"]["recurrence"]["isActive"] is False
        # Other fields preserved
        assert variables["input"]["recurrence"]["frequency"] == "monthly"
        assert variables["input"]["recurrence"]["amount"] == -15.99
        assert variables["input"]["recurrence"]["baseDate"] == "2024-03-18"

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_already_inactive(self, mock_get_client):
        """Returns success message when stream is already inactive."""
        merchant = _make_merchant()
        merchant["merchant"]["recurringTransactionStream"]["isActive"] = False
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = merchant
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert "already inactive" in parsed["message"].lower()
        # Should NOT have made a second (mutation) call
        assert mock_client.gql_call.call_count == 1

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_merchant_not_found(self, mock_get_client):
        """Returns error when merchant doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="bad_id")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "not found" in parsed["message"]

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_no_recurring_stream(self, mock_get_client):
        """Returns error when merchant has no recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(stream=None)
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "no recurring" in parsed["message"].lower()

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_api_errors(self, mock_get_client):
        """API errors from mutation are returned."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(),
            {
                "updateMerchant": {
                    "merchant": None,
                    "errors": {"message": "Server error", "code": "INTERNAL"},
                }
            },
        ]
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "errors" in parsed

    @patch("monarch_mcp_server.server.get_monarch_client")
    def test_exception_handling(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Timeout")

        result = disable_recurring_transaction(merchant_id="merch_1")

        assert "Error disabling recurring transaction:" in result
        assert "Timeout" in result
