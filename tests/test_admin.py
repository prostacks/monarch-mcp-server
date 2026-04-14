"""Tests for admin routes (Phase 4): /admin/status and /admin/reauth."""

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from monarch_mcp_server.admin import (
    _admin_sessions,
    _create_admin_token,
    _validate_admin_password,
    _validate_admin_token,
    handle_reauth_get,
    handle_reauth_post,
    handle_status_get,
    handle_status_post,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_PASSWORD = "test-admin-password-123"


def _make_request(form_data: dict | None = None):
    """Create a mock Starlette Request with optional form data."""
    request = AsyncMock()
    if form_data is not None:
        form_mock = AsyncMock(return_value=form_data)
        request.form = form_mock
    return request


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------


class TestValidateAdminPassword:
    def test_correct_password(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            assert _validate_admin_password(TEST_PASSWORD) is True

    def test_wrong_password(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            assert _validate_admin_password("wrong") is False

    def test_no_env_var(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _validate_admin_password("anything") is False

    def test_empty_env_var(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": ""}):
            assert _validate_admin_password("") is False


# ---------------------------------------------------------------------------
# Admin session tokens
# ---------------------------------------------------------------------------


class TestAdminTokens:
    def setup_method(self):
        _admin_sessions.clear()

    def test_create_and_validate_token(self):
        token = _create_admin_token()
        assert isinstance(token, str)
        assert len(token) > 20
        assert _validate_admin_token(token) is True

    def test_invalid_token_rejected(self):
        assert _validate_admin_token("nonexistent-token") is False

    def test_expired_token_rejected(self):
        token = _create_admin_token()
        # Backdate the creation time beyond the 10-minute window
        _admin_sessions[token] = time.time() - 700
        assert _validate_admin_token(token) is False

    def test_cleanup_old_sessions(self):
        # Manually insert an old session
        _admin_sessions["old-token"] = time.time() - 700
        # Creating a new token should clean up the old one
        _create_admin_token()
        assert "old-token" not in _admin_sessions


# ---------------------------------------------------------------------------
# GET /admin/status
# ---------------------------------------------------------------------------


class TestStatusGet:
    @pytest.mark.asyncio
    async def test_returns_password_form(self):
        request = _make_request()
        response = await handle_status_get(request)
        assert response.status_code == 200
        body = response.body.decode()
        assert "admin_password" in body
        assert "Server Password" in body
        assert "/admin/status" in body


# ---------------------------------------------------------------------------
# POST /admin/status
# ---------------------------------------------------------------------------


class TestStatusPost:
    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request({"admin_password": "wrong"})
            response = await handle_status_post(request)
            assert response.status_code == 401
            body = response.body.decode()
            assert "Invalid password" in body

    @pytest.mark.asyncio
    async def test_correct_password_shows_status(self):
        mock_status = {
            "has_in_memory_token": True,
            "in_memory_updated_at": "2026-04-10T12:00:00+00:00",
            "has_env_var_token": False,
            "keyring_available": False,
            "has_keyring_token": False,
            "has_any_token": True,
        }
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch(
                "monarch_mcp_server.secure_session.secure_session"
            ) as mock_session:
                mock_session.get_token_status.return_value = mock_status
                request = _make_request({"admin_password": TEST_PASSWORD})
                response = await handle_status_post(request)
                assert response.status_code == 200
                body = response.body.decode()
                assert "Token Status" in body
                assert "In-Memory Token" in body
                assert "Active" in body
                assert "/admin/reauth" in body


# ---------------------------------------------------------------------------
# GET /admin/reauth
# ---------------------------------------------------------------------------


class TestReauthGet:
    @pytest.mark.asyncio
    async def test_returns_password_form(self):
        request = _make_request()
        response = await handle_reauth_get(request)
        assert response.status_code == 200
        body = response.body.decode()
        assert "admin_password" in body
        assert "/admin/reauth" in body


# ---------------------------------------------------------------------------
# POST /admin/reauth - Step 1: admin_auth
# ---------------------------------------------------------------------------


class TestReauthAdminAuth:
    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request({"step": "admin_auth", "admin_password": "wrong"})
            response = await handle_reauth_post(request)
            assert response.status_code == 401
            body = response.body.decode()
            assert "Invalid password" in body

    @pytest.mark.asyncio
    async def test_correct_password_shows_monarch_login_form(self):
        _admin_sessions.clear()
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request(
                {"step": "admin_auth", "admin_password": TEST_PASSWORD}
            )
            response = await handle_reauth_post(request)
            assert response.status_code == 200
            body = response.body.decode()
            assert "Monarch Money" in body
            assert "email" in body
            assert "password" in body
            assert "admin_token" in body


# ---------------------------------------------------------------------------
# POST /admin/reauth - Step 2: monarch_login
# ---------------------------------------------------------------------------


class TestReauthMonarchLogin:
    def setup_method(self):
        _admin_sessions.clear()

    @pytest.mark.asyncio
    async def test_expired_admin_token_returns_401(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request(
                {
                    "step": "monarch_login",
                    "admin_token": "expired-token",
                    "email": "user@example.com",
                    "password": "monarch-pass",
                }
            )
            response = await handle_reauth_post(request)
            assert response.status_code == 401
            assert "expired" in response.body.decode().lower()

    @pytest.mark.asyncio
    async def test_missing_email_returns_400(self):
        admin_token = _create_admin_token()
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request(
                {
                    "step": "monarch_login",
                    "admin_token": admin_token,
                    "email": "",
                    "password": "monarch-pass",
                }
            )
            response = await handle_reauth_post(request)
            assert response.status_code == 400
            assert "required" in response.body.decode().lower()

    @pytest.mark.asyncio
    async def test_successful_login_updates_token(self):
        admin_token = _create_admin_token()

        mock_mm = MagicMock()
        mock_mm.token = "new-monarch-token-abc"
        mock_mm.login = AsyncMock()

        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch("monarchmoney.MonarchMoney", return_value=mock_mm):
                with patch(
                    "monarch_mcp_server.secure_session.secure_session"
                ) as mock_session:
                    request = _make_request(
                        {
                            "step": "monarch_login",
                            "admin_token": admin_token,
                            "email": "user@example.com",
                            "password": "monarch-pass",
                        }
                    )
                    response = await handle_reauth_post(request)
                    assert response.status_code == 200
                    body = response.body.decode()
                    assert "successful" in body.lower()
                    mock_session.update_token_in_memory.assert_called_once_with(
                        "new-monarch-token-abc"
                    )

    @pytest.mark.asyncio
    async def test_login_requires_mfa_shows_mfa_form(self):
        admin_token = _create_admin_token()

        mock_mm = MagicMock()
        mock_mm.login = AsyncMock(
            side_effect=sys.modules["monarchmoney"].RequireMFAException("MFA required")
        )

        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch("monarchmoney.MonarchMoney", return_value=mock_mm):
                request = _make_request(
                    {
                        "step": "monarch_login",
                        "admin_token": admin_token,
                        "email": "user@example.com",
                        "password": "monarch-pass",
                    }
                )
                response = await handle_reauth_post(request)
                assert response.status_code == 200
                body = response.body.decode()
                assert "MFA" in body or "mfa" in body
                assert "mfa_code" in body

    @pytest.mark.asyncio
    async def test_login_failure_shows_error(self):
        admin_token = _create_admin_token()

        mock_mm = MagicMock()
        mock_mm.login = AsyncMock(side_effect=Exception("Invalid credentials"))

        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch("monarchmoney.MonarchMoney", return_value=mock_mm):
                request = _make_request(
                    {
                        "step": "monarch_login",
                        "admin_token": admin_token,
                        "email": "user@example.com",
                        "password": "wrong-pass",
                    }
                )
                response = await handle_reauth_post(request)
                assert response.status_code == 401
                body = response.body.decode()
                assert "Invalid credentials" in body


# ---------------------------------------------------------------------------
# POST /admin/reauth - Step 3: mfa
# ---------------------------------------------------------------------------


class TestReauthMFA:
    def setup_method(self):
        _admin_sessions.clear()

    @pytest.mark.asyncio
    async def test_expired_admin_token_returns_401(self):
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request(
                {
                    "step": "mfa",
                    "admin_token": "expired-token",
                    "email": "user@example.com",
                    "password": "monarch-pass",
                    "mfa_code": "123456",
                }
            )
            response = await handle_reauth_post(request)
            assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_mfa_code_returns_400(self):
        admin_token = _create_admin_token()
        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            request = _make_request(
                {
                    "step": "mfa",
                    "admin_token": admin_token,
                    "email": "user@example.com",
                    "password": "monarch-pass",
                    "mfa_code": "",
                }
            )
            response = await handle_reauth_post(request)
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_successful_mfa_updates_token(self):
        admin_token = _create_admin_token()

        mock_mm = MagicMock()
        mock_mm.token = "new-token-after-mfa"
        mock_mm.multi_factor_authenticate = AsyncMock()

        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch("monarchmoney.MonarchMoney", return_value=mock_mm):
                with patch(
                    "monarch_mcp_server.secure_session.secure_session"
                ) as mock_session:
                    request = _make_request(
                        {
                            "step": "mfa",
                            "admin_token": admin_token,
                            "email": "user@example.com",
                            "password": "monarch-pass",
                            "mfa_code": "123456",
                        }
                    )
                    response = await handle_reauth_post(request)
                    assert response.status_code == 200
                    body = response.body.decode()
                    assert "successful" in body.lower()
                    mock_session.update_token_in_memory.assert_called_once_with(
                        "new-token-after-mfa"
                    )

    @pytest.mark.asyncio
    async def test_mfa_failure_shows_error(self):
        admin_token = _create_admin_token()

        mock_mm = MagicMock()
        mock_mm.multi_factor_authenticate = AsyncMock(
            side_effect=Exception("Invalid MFA code")
        )

        with patch.dict(os.environ, {"MCP_AUTH_PASSWORD": TEST_PASSWORD}):
            with patch("monarchmoney.MonarchMoney", return_value=mock_mm):
                request = _make_request(
                    {
                        "step": "mfa",
                        "admin_token": admin_token,
                        "email": "user@example.com",
                        "password": "monarch-pass",
                        "mfa_code": "000000",
                    }
                )
                response = await handle_reauth_post(request)
                assert response.status_code == 401
                body = response.body.decode()
                assert "Invalid MFA code" in body


# ---------------------------------------------------------------------------
# POST /admin/reauth - Unknown step
# ---------------------------------------------------------------------------


class TestReauthUnknownStep:
    @pytest.mark.asyncio
    async def test_unknown_step_returns_400(self):
        request = _make_request({"step": "unknown_step"})
        response = await handle_reauth_post(request)
        assert response.status_code == 400
        assert "Invalid request" in response.body.decode()
