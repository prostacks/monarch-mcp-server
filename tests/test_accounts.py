"""Tests for get_accounts MCP tool with enriched fields and payment details."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from monarch_mcp_server.tools.accounts import get_accounts


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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_depository_no_payment_details(self, mock_get_client):
        """Depository accounts (checking/savings) do NOT get a payment_details key."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": [_make_checking()]}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        assert "payment_details" not in accounts[0]

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
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

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_empty_accounts_list(self, mock_get_client):
        """Edge case: API returns zero accounts."""
        mock_client = AsyncMock()
        mock_client.gql_call.return_value = {"accounts": []}
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert accounts == []

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_error_handling_both_paths_fail(self, mock_get_client):
        """If both custom query and library fallback fail, returns error message."""
        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = Exception("GraphQL error")
        mock_client.get_accounts.side_effect = Exception("Network timeout")
        mock_get_client.return_value = mock_client

        result = get_accounts()

        assert result.startswith("Error getting accounts:")
        assert "Network timeout" in result


# ---------------------------------------------------------------------------
# Due day enrichment from recurring transactions
# ---------------------------------------------------------------------------


def _make_recurring_item(account_id, date, is_past=False, amount=-50.0, base_date=None):
    """Build a mock recurring transaction item for due_day tests."""
    return {
        "date": date,
        "amount": amount,
        "isPast": is_past,
        "transactionId": None,
        "amountDiff": None,
        "isLate": False,
        "isCompleted": False,
        "markedPaidAt": None,
        "stream": {
            "id": f"stream_{account_id}",
            "frequency": "monthly",
            "amount": amount,
            "isApproximate": False,
            "isActive": True,
            "name": "Test Merchant",
            "logoUrl": None,
            "baseDate": base_date or date,
            "reviewStatus": "automatic_approved",
            "recurringType": "expense",
            "merchant": {"id": "merch_1", "name": "Test Merchant", "logoUrl": None},
        },
        "category": {"id": "cat_1", "name": "Bills"},
        "account": {"id": account_id, "displayName": "Test Account", "logoUrl": None},
    }


def _mock_gql_call(accounts, recurring_items):
    """Create a side_effect function that returns accounts for the first call
    and recurring items for the second call (recurring query)."""
    call_count = {"n": 0}

    async def _side_effect(*args, **kwargs):
        call_count["n"] += 1
        operation = kwargs.get("operation", "")
        if operation == "GetAccountsWithPaymentFields" or call_count["n"] == 1:
            return {"accounts": accounts}
        else:
            return {"recurringTransactionItems": recurring_items}

    return _side_effect


class TestGetAccountsDueDay:
    """Tests for due_day enrichment from recurring transactions."""

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_populated_for_credit_card(self, mock_get_client):
        """Credit card gets due_day from recurring transaction date."""
        cc = _make_credit_card()
        recurring = [_make_recurring_item("acc_cc", "2026-05-15")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        assert pd["due_day"] == 15
        assert pd["recurring_merchant_id"] == "merch_1"
        assert pd["recurring_stream_id"] == "stream_acc_cc"
        # Other payment fields still present
        assert pd["minimum_payment"] == 75.0
        assert pd["apr"] == 25.7

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_populated_for_loan(self, mock_get_client):
        """Loan gets due_day from recurring transaction date."""
        loan = _make_loan()
        recurring = [_make_recurring_item("acc_loan", "2026-05-02")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([loan], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        assert pd["due_day"] == 2
        assert pd["recurring_merchant_id"] == "merch_1"
        assert pd["recurring_stream_id"] == "stream_acc_loan"
        assert pd["minimum_payment"] == 520.0

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_no_due_day_for_depository(self, mock_get_client):
        """Depository accounts don't get due_day even if recurring exists."""
        chk = _make_checking()
        # Even with a recurring item for this account, it shouldn't get due_day
        recurring = [_make_recurring_item("acc_chk", "2026-05-10")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([chk], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        assert "payment_details" not in accounts[0]

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_missing_when_no_recurring_match(self, mock_get_client):
        """Credit card without matching recurring item has no due_day."""
        cc = _make_credit_card()
        # Recurring item for a DIFFERENT account
        recurring = [_make_recurring_item("acc_other", "2026-05-20")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        # Has payment fields but no due_day
        assert pd["minimum_payment"] == 75.0
        assert "due_day" not in pd

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_mixed_accounts_selective_due_day(self, mock_get_client):
        """Mixed accounts: only credit/loan get due_day, and only when matched."""
        chk = _make_checking()
        cc = _make_credit_card()
        loan = _make_loan()
        recurring = [
            _make_recurring_item("acc_cc", "2026-05-15"),
            # No recurring for the loan
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([chk, cc, loan], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 3
        # Checking: no payment_details at all
        assert "payment_details" not in accounts[0]
        # Credit card: has due_day and recurring IDs
        assert accounts[1]["payment_details"]["due_day"] == 15
        assert accounts[1]["payment_details"]["recurring_merchant_id"] == "merch_1"
        assert accounts[1]["payment_details"]["recurring_stream_id"] == "stream_acc_cc"
        # Loan: has payment_details but no due_day
        assert "due_day" not in accounts[2]["payment_details"]

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_uses_first_item_per_account(self, mock_get_client):
        """When multiple recurring items exist for same account, uses the first one."""
        cc = _make_credit_card()
        recurring = [
            _make_recurring_item("acc_cc", "2026-04-15"),  # first match
            _make_recurring_item("acc_cc", "2026-05-15"),  # second match (ignored)
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        # Should use first item's date (day 15)
        assert accounts[0]["payment_details"]["due_day"] == 15

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_graceful_on_recurring_fetch_failure(self, mock_get_client):
        """If recurring fetch fails, accounts still returned without due_day."""
        cc = _make_credit_card()

        call_count = {"n": 0}

        async def _failing_recurring(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"accounts": [cc]}
            else:
                raise Exception("Recurring API error")

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _failing_recurring
        # Also make the library fallback for recurring fail
        mock_client.get_recurring_transactions.side_effect = Exception(
            "Library also failed"
        )
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        # Account still returned with payment_details, just no due_day
        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        assert pd["minimum_payment"] == 75.0
        assert "due_day" not in pd

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_creates_payment_details_if_missing(self, mock_get_client):
        """If a credit account has no payment fields but has recurring, payment_details
        is created with just due_day."""
        # Credit card with all payment fields as None
        cc = _make_credit_card(minimum_payment=None, apr=None, limit=None)
        recurring = [_make_recurring_item("acc_cc", "2026-05-25")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        # payment_details should exist with due_day and recurring IDs
        pd = accounts[0]["payment_details"]
        assert pd["due_day"] == 25
        assert pd["recurring_merchant_id"] == "merch_1"
        assert pd["recurring_stream_id"] == "stream_acc_cc"

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_prefers_base_date_over_item_date(self, mock_get_client):
        """When stream.baseDate differs from item.date, baseDate is used for due_day."""
        cc = _make_credit_card()
        # item.date is the 2nd but stream.baseDate is the 8th
        # (mirrors real Amazon data: item.date=2026-04-02, baseDate=2026-04-08)
        recurring = [
            _make_recurring_item("acc_cc", "2026-04-02", base_date="2026-04-08")
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], recurring)
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        # Should use baseDate (day 8), not item.date (day 2)
        assert accounts[0]["payment_details"]["due_day"] == 8

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_due_day_falls_back_to_item_date_when_no_base_date(self, mock_get_client):
        """When stream.baseDate is null, falls back to item.date for due_day."""
        cc = _make_credit_card()
        recurring_item = _make_recurring_item("acc_cc", "2026-05-20")
        # Simulate missing baseDate (e.g., library fallback)
        recurring_item["stream"]["baseDate"] = None

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call([cc], [recurring_item])
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        # Falls back to item.date (day 20)
        assert accounts[0]["payment_details"]["due_day"] == 20


# ---------------------------------------------------------------------------
# Streams fallback for due_day (B3 Part 2)
# ---------------------------------------------------------------------------


def _make_stream_response(
    account_id,
    base_date,
    merchant_id="merch_s1",
    stream_id=None,
    frequency="monthly",
    amount=-100.0,
):
    """Build a mock recurring stream for the streams fallback query."""
    return {
        "id": stream_id or f"stream_{account_id}",
        "name": "Stream Merchant",
        "frequency": frequency,
        "amount": amount,
        "baseDate": base_date,
        "isActive": True,
        "isApproximate": False,
        "logoUrl": None,
        "reviewStatus": "approved",
        "recurringType": "expense",
        "merchant": {"id": merchant_id, "name": "Stream Merchant", "logoUrl": None},
        "account": {"id": account_id, "displayName": "Test Account"},
        "category": {"id": "cat_1", "name": "Bills"},
        "nextForecastedTransaction": None,
    }


def _mock_gql_call_with_streams(accounts, recurring_items, streams):
    """Create a side_effect that returns accounts, then items, then streams.

    The three gql_call invocations are dispatched by operation name:
    - GetAccountsWithPaymentFields -> accounts
    - Web_GetUpcomingRecurringTransactionItems -> recurring items
    - Common_GetAllRecurringTransactionItems -> streams
    """

    async def _side_effect(*args, **kwargs):
        operation = kwargs.get("operation", "")
        if operation == "GetAccountsWithPaymentFields":
            return {"accounts": accounts}
        elif operation == "Web_GetUpcomingRecurringTransactionItems":
            return {"recurringTransactionItems": recurring_items}
        elif operation == "Common_GetAllRecurringTransactionItems":
            return {"recurringTransactionStreams": streams}
        return {}

    return _side_effect


class TestGetAccountsDueDayStreamsFallback:
    """Tests for the Phase 2 streams fallback in _fetch_due_days."""

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_streams_fallback_fills_missing_due_day(self, mock_get_client):
        """Loan with no recurring items but a stream gets due_day from streams fallback."""
        loan = _make_loan()
        # No recurring items for this account
        recurring_items = []
        # But there IS a stream
        streams = [
            _make_stream_response(
                "acc_loan", "2026-04-02", merchant_id="merch_lc", amount=-520.0
            )
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call_with_streams(
            [loan], recurring_items, streams
        )
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        assert pd["due_day"] == 2
        assert pd["recurring_merchant_id"] == "merch_lc"
        assert pd["recurring_stream_id"] == "stream_acc_loan"

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_streams_fallback_not_called_when_all_accounts_resolved(
        self, mock_get_client
    ):
        """When all credit/loan accounts have due_day from items, streams query is skipped."""
        cc = _make_credit_card()
        recurring_items = [_make_recurring_item("acc_cc", "2026-05-15")]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call_with_streams(
            [cc],
            recurring_items,
            [],  # streams shouldn't be called
        )
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert accounts[0]["payment_details"]["due_day"] == 15

        # Verify only 2 gql_call invocations (accounts + items), NOT 3
        assert mock_client.gql_call.call_count == 2

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_mixed_items_and_streams_fallback(self, mock_get_client):
        """Credit card resolved by items, loan resolved by streams fallback."""
        cc = _make_credit_card()
        loan = _make_loan()
        # Items only have the credit card
        recurring_items = [_make_recurring_item("acc_cc", "2026-05-15")]
        # Streams have the loan
        streams = [
            _make_stream_response("acc_loan", "2026-04-02", merchant_id="merch_lc")
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call_with_streams(
            [cc, loan], recurring_items, streams
        )
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 2
        # Credit card: from items
        assert accounts[0]["payment_details"]["due_day"] == 15
        assert accounts[0]["payment_details"]["recurring_merchant_id"] == "merch_1"
        # Loan: from streams fallback
        assert accounts[1]["payment_details"]["due_day"] == 2
        assert accounts[1]["payment_details"]["recurring_merchant_id"] == "merch_lc"

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_streams_fallback_graceful_on_failure(self, mock_get_client):
        """If streams fallback fails, accounts still returned without due_day."""
        loan = _make_loan()
        recurring_items = []  # No items for the loan

        call_count = {"n": 0}

        async def _failing_streams(*args, **kwargs):
            call_count["n"] += 1
            operation = kwargs.get("operation", "")
            if operation == "GetAccountsWithPaymentFields":
                return {"accounts": [loan]}
            elif operation == "Web_GetUpcomingRecurringTransactionItems":
                return {"recurringTransactionItems": []}
            elif operation == "Common_GetAllRecurringTransactionItems":
                raise Exception("Streams API error")
            return {}

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _failing_streams
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        # Account still returned with payment_details, just no due_day
        assert len(accounts) == 1
        pd = accounts[0]["payment_details"]
        assert pd["minimum_payment"] == 520.0
        assert "due_day" not in pd

    @patch("monarch_mcp_server.tools.accounts.get_monarch_client")
    def test_streams_fallback_ignores_non_credit_loan_accounts(self, mock_get_client):
        """Streams for depository accounts are ignored even in fallback."""
        chk = _make_checking()
        loan = _make_loan()
        recurring_items = []
        # Stream exists for both checking and loan
        streams = [
            _make_stream_response("acc_chk", "2026-04-10"),
            _make_stream_response("acc_loan", "2026-04-02"),
        ]

        mock_client = AsyncMock()
        mock_client.gql_call.side_effect = _mock_gql_call_with_streams(
            [chk, loan], recurring_items, streams
        )
        mock_get_client.return_value = mock_client

        result = get_accounts()
        accounts = json.loads(result)

        assert len(accounts) == 2
        # Checking: no payment_details (depository accounts excluded from enrichment)
        assert "payment_details" not in accounts[0]
        # Loan: gets due_day from streams fallback
        assert accounts[1]["payment_details"]["due_day"] == 2
