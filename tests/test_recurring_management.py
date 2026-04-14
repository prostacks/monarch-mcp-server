"""Tests for merchant & recurring transaction management tools:
get_merchant_details, get_recurring_streams, update_recurring_transaction,
disable_recurring_transaction."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from monarch_mcp_server.tools.recurring import (
    get_merchant_details,
    get_recurring_streams,
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_merchant_not_found(self, mock_get_client):
        """Returns error when merchant doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = get_merchant_details(merchant_id="bad_id")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "not found" in parsed["message"]

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_exception_handling(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Network error")

        result = get_merchant_details(merchant_id="merch_1")

        assert "Error getting merchant details:" in result
        assert "Network error" in result


# ---------------------------------------------------------------------------
# TestGetRecurringStreams
# ---------------------------------------------------------------------------


class TestGetRecurringStreams:
    """Tests for get_recurring_streams tool (items-based with deduplication)."""

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_deduplicates_by_stream_id(self, mock_get_client):
        """Multiple items with same stream ID produce one stream entry."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "recurringTransactionItems": [
                {
                    "stream": {
                        "id": "stream_1",
                        "name": "Netflix",
                        "frequency": "monthly",
                        "amount": -15.99,
                        "baseDate": "2026-04-15",
                        "isActive": True,
                        "isApproximate": False,
                        "logoUrl": "https://logo.com/netflix.png",
                        "reviewStatus": "automatic_approved",
                        "recurringType": "expense",
                        "merchant": {
                            "id": "merch_1",
                            "name": "Netflix",
                            "logoUrl": "https://logo.com/netflix.png",
                        },
                    },
                    "date": "2026-04-15",
                    "amount": -15.99,
                    "account": {"id": "acc_1", "displayName": "Chase Sapphire"},
                    "category": {"id": "cat_1", "name": "Entertainment"},
                },
                {
                    "stream": {
                        "id": "stream_1",  # Same stream, different item date
                        "name": "Netflix",
                        "frequency": "monthly",
                        "amount": -15.99,
                        "baseDate": "2026-04-15",
                        "isActive": True,
                        "isApproximate": False,
                        "logoUrl": "https://logo.com/netflix.png",
                        "reviewStatus": "automatic_approved",
                        "recurringType": "expense",
                        "merchant": {
                            "id": "merch_1",
                            "name": "Netflix",
                            "logoUrl": "https://logo.com/netflix.png",
                        },
                    },
                    "date": "2026-05-15",
                    "amount": -15.99,
                    "account": {"id": "acc_1", "displayName": "Chase Sapphire"},
                    "category": {"id": "cat_1", "name": "Entertainment"},
                },
                {
                    "stream": {
                        "id": "stream_2",
                        "name": "Lending Club",
                        "frequency": "monthly",
                        "amount": -520.0,
                        "baseDate": "2026-04-02",
                        "isActive": True,
                        "isApproximate": False,
                        "logoUrl": None,
                        "reviewStatus": "approved",
                        "recurringType": "expense",
                        "merchant": {
                            "id": "merch_2",
                            "name": "Lending Club",
                            "logoUrl": None,
                        },
                    },
                    "date": "2026-04-02",
                    "amount": -520.0,
                    "account": {"id": "acc_2", "displayName": "Personal Loan"},
                    "category": {"id": "cat_2", "name": "Loan Payment"},
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_recurring_streams()
        streams = json.loads(result)

        # 3 items but only 2 unique streams
        assert len(streams) == 2

        # Netflix stream
        s1 = streams[0]
        assert s1["id"] == "stream_1"
        assert s1["name"] == "Netflix"
        assert s1["frequency"] == "monthly"
        assert s1["amount"] == -15.99
        assert s1["base_date"] == "2026-04-15"
        assert s1["is_active"] is True
        assert s1["recurring_type"] == "expense"
        assert s1["merchant"]["id"] == "merch_1"
        assert s1["account"]["id"] == "acc_1"
        assert s1["category"]["name"] == "Entertainment"

        # Lending Club stream
        s2 = streams[1]
        assert s2["id"] == "stream_2"
        assert s2["name"] == "Lending Club"
        assert s2["amount"] == -520.0
        assert s2["merchant"]["id"] == "merch_2"
        assert s2["account"]["name"] == "Personal Loan"

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_empty(self, mock_get_client):
        """Test when no items/streams exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"recurringTransactionItems": []}
        mock_get_client.return_value = mock_client

        result = get_recurring_streams()
        streams = json.loads(result)

        assert streams == []

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_null_optional_fields(self, mock_get_client):
        """Test stream with null merchant, account, category."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "recurringTransactionItems": [
                {
                    "stream": {
                        "id": "stream_3",
                        "name": "Unknown",
                        "frequency": "monthly",
                        "amount": -10.0,
                        "baseDate": "2026-04-01",
                        "isActive": True,
                        "isApproximate": True,
                        "logoUrl": None,
                        "reviewStatus": None,
                        "recurringType": "expense",
                        "merchant": None,
                    },
                    "date": "2026-04-01",
                    "amount": -10.0,
                    "account": None,
                    "category": None,
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_recurring_streams()
        streams = json.loads(result)

        assert len(streams) == 1
        s = streams[0]
        assert s["merchant"] is None
        assert s["account"] is None
        assert s["category"] is None
        assert s["is_approximate"] is True

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_uses_wide_date_range(self, mock_get_client):
        """Verify wide date range (2020-2030) is used for maximum coverage."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"recurringTransactionItems": []}
        mock_get_client.return_value = mock_client

        get_recurring_streams()

        call_kwargs = mock_client.gql_call.call_args[1]
        assert call_kwargs["variables"]["startDate"] == "2020-01-01"
        assert call_kwargs["variables"]["endDate"] == "2030-12-31"

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_filters_inactive(self, mock_get_client):
        """include_inactive=False filters out inactive streams."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {
            "recurringTransactionItems": [
                {
                    "stream": {
                        "id": "stream_active",
                        "name": "Active",
                        "frequency": "monthly",
                        "amount": -10.0,
                        "baseDate": "2026-04-01",
                        "isActive": True,
                        "isApproximate": False,
                        "logoUrl": None,
                        "reviewStatus": None,
                        "recurringType": "expense",
                        "merchant": {"id": "m1", "name": "M1", "logoUrl": None},
                    },
                    "date": "2026-04-01",
                    "amount": -10.0,
                    "account": {"id": "a1", "displayName": "Acct"},
                    "category": {"id": "c1", "name": "Cat"},
                },
                {
                    "stream": {
                        "id": "stream_inactive",
                        "name": "Inactive",
                        "frequency": "monthly",
                        "amount": -20.0,
                        "baseDate": "2026-04-01",
                        "isActive": False,
                        "isApproximate": False,
                        "logoUrl": None,
                        "reviewStatus": None,
                        "recurringType": "expense",
                        "merchant": {"id": "m2", "name": "M2", "logoUrl": None},
                    },
                    "date": "2026-04-01",
                    "amount": -20.0,
                    "account": {"id": "a2", "displayName": "Acct2"},
                    "category": {"id": "c2", "name": "Cat2"},
                },
            ]
        }
        mock_get_client.return_value = mock_client

        # With include_inactive=True (default), both returned
        result = get_recurring_streams(include_inactive=True)
        assert len(json.loads(result)) == 2

        # With include_inactive=False, only active
        result = get_recurring_streams(include_inactive=False)
        streams = json.loads(result)
        assert len(streams) == 1
        assert streams[0]["name"] == "Active"

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_get_streams_error(self, mock_get_client):
        """Test error handling."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        result = get_recurring_streams()

        assert "Error getting recurring streams" in result


# ---------------------------------------------------------------------------
# TestUpdateRecurringTransaction
# ---------------------------------------------------------------------------


class TestUpdateRecurringTransaction:
    """Tests for update_recurring_transaction tool."""

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_no_stream_missing_all_required_fields(self, mock_get_client):
        """No stream + missing frequency/base_date/amount returns error listing all three."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(stream=None)
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(merchant_id="merch_1", is_active=False)
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "no recurring" in parsed["message"].lower()
        assert "frequency" in parsed["message"]
        assert "base_date" in parsed["message"]
        assert "amount" in parsed["message"]

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_no_stream_missing_some_required_fields(self, mock_get_client):
        """No stream + only frequency provided still lists missing base_date and amount."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(stream=None)
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1", frequency="monthly"
        )
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "base_date" in parsed["message"]
        assert "amount" in parsed["message"]
        # frequency was provided, so it should NOT be listed as missing
        assert "frequency" not in parsed["message"].split("provide: ")[1]

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_no_stream_creates_stream_with_required_fields(self, mock_get_client):
        """No stream + all required fields creates a new stream via mutation."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(stream=None),  # GET: no existing stream
            _make_update_response(
                name="Netflix",
                frequency="monthly",
                amount=-15.99,
                base_date="2024-01-15",
                is_active=True,
            ),
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1",
            frequency="monthly",
            base_date="2024-01-15",
            amount=-15.99,
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["recurring_stream"]["frequency"] == "monthly"
        assert parsed["recurring_stream"]["base_date"] == "2024-01-15"
        assert parsed["recurring_stream"]["amount"] == -15.99
        assert parsed["recurring_stream"]["is_active"] is True

        # Verify mutation variables
        mutation_call = mock_client.gql_call.call_args_list[1]
        variables = mutation_call.kwargs["variables"]
        recurrence = variables["input"]["recurrence"]
        assert recurrence["isRecurring"] is True
        assert recurrence["frequency"] == "monthly"
        assert recurrence["baseDate"] == "2024-01-15"
        assert recurrence["amount"] == -15.99
        assert recurrence["isActive"] is True
        # Name preserved from merchant when not explicitly provided
        assert variables["input"]["name"] == "Netflix"

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_no_stream_creates_with_custom_name_and_inactive(self, mock_get_client):
        """No stream + custom name + is_active=False creates stream correctly."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = [
            _make_merchant(stream=None),
            _make_update_response(
                name="Netflix Premium",
                frequency="bimonthly",
                amount=-22.99,
                base_date="2024-02-01",
                is_active=False,
            ),
        ]
        mock_get_client.return_value = mock_client

        result = update_recurring_transaction(
            merchant_id="merch_1",
            name="Netflix Premium",
            frequency="bimonthly",
            base_date="2024-02-01",
            amount=-22.99,
            is_active=False,
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["merchant"]["name"] == "Netflix Premium"
        assert parsed["recurring_stream"]["is_active"] is False

        # Verify custom name and is_active override
        mutation_call = mock_client.gql_call.call_args_list[1]
        variables = mutation_call.kwargs["variables"]
        assert variables["input"]["name"] == "Netflix Premium"
        assert variables["input"]["recurrence"]["isActive"] is False

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_merchant_not_found(self, mock_get_client):
        """Returns error when merchant doesn't exist."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"merchant": None}
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="bad_id")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "not found" in parsed["message"]

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_no_recurring_stream(self, mock_get_client):
        """Returns error when merchant has no recurring stream."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = _make_merchant(stream=None)
        mock_get_client.return_value = mock_client

        result = disable_recurring_transaction(merchant_id="merch_1")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "no recurring" in parsed["message"].lower()

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.recurring.get_monarch_client")
    def test_exception_handling(self, mock_get_client):
        """Exception returns error message string."""
        mock_get_client.side_effect = RuntimeError("Timeout")

        result = disable_recurring_transaction(merchant_id="merch_1")

        assert "Error disabling recurring transaction:" in result
        assert "Timeout" in result
