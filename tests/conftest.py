"""Shared test configuration and mocks for the Monarch MCP Server test suite.

This module sets up the monarchmoney module mock BEFORE any test files import
from monarch_mcp_server. The mock must be in place before import time because
server.py does `from monarchmoney import MonarchMoney, MonarchMoneyEndpoints, RequireMFAException`
at the top level.

IMPORTANT: RequireMFAException is created as a proper Exception subclass using type().
Do NOT set it to bare `Exception` -- that would make `except RequireMFAException`
catch ALL exceptions, masking real bugs in the admin re-auth flow.
"""

import sys
from unittest.mock import MagicMock

# Create the monarchmoney mock module before any monarch_mcp_server imports
_mock_mm = MagicMock()
_mock_mm.MonarchMoney = MagicMock
_mock_mm.MonarchMoneyEndpoints = MagicMock()
_mock_mm.RequireMFAException = type("RequireMFAException", (Exception,), {})

sys.modules["monarchmoney"] = _mock_mm
