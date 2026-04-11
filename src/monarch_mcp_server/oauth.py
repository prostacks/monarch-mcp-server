"""
OAuth 2.1 Authorization Server provider for the Monarch MCP Server.

Implements the MCP SDK's OAuthAuthorizationServerProvider protocol with:
- Pre-shared client credentials (no Dynamic Client Registration)
- Simple password gate for authorization consent
- In-memory token storage (single-user, personal server)
- PKCE enforcement (handled by the SDK)
- Short-lived access tokens (1 hour) with refresh token support (30 days)
"""

import logging
import os
import secrets
import time
from typing import Optional

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

# Token lifetimes
ACCESS_TOKEN_LIFETIME = 3600  # 1 hour in seconds
REFRESH_TOKEN_LIFETIME = 30 * 24 * 3600  # 30 days in seconds
AUTH_CODE_LIFETIME = 300  # 5 minutes in seconds

# Environment variable names
MCP_CLIENT_ID_ENV = "MCP_CLIENT_ID"
MCP_CLIENT_SECRET_ENV = "MCP_CLIENT_SECRET"
MCP_AUTH_PASSWORD_ENV = "MCP_AUTH_PASSWORD"
MCP_SERVER_URL_ENV = "MCP_SERVER_URL"


class MonarchOAuthProvider:
    """OAuth 2.1 Authorization Server for the Monarch MCP Server.

    This provider:
    - Only accepts a single pre-shared client (no DCR)
    - Uses a password gate for user consent (authorize step)
    - Stores tokens in memory (no database needed for single-user)
    - Issues short-lived access tokens with refresh token rotation
    """

    def __init__(self) -> None:
        # In-memory stores
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

        # Pending authorization sessions (auth_session_id -> AuthorizationParams)
        self._pending_authorizations: dict[str, dict] = {}

        # Pre-shared client credentials from env vars
        self._client_id = os.environ.get(MCP_CLIENT_ID_ENV, "")
        self._client_secret = os.environ.get(MCP_CLIENT_SECRET_ENV, "")
        self._auth_password = os.environ.get(MCP_AUTH_PASSWORD_ENV, "")
        self._server_url = os.environ.get(MCP_SERVER_URL_ENV, "")

        if not self._client_id or not self._client_secret:
            logger.warning(
                f"OAuth client credentials not configured. "
                f"Set {MCP_CLIENT_ID_ENV} and {MCP_CLIENT_SECRET_ENV} environment variables."
            )
        if not self._auth_password:
            logger.warning(
                f"OAuth auth password not configured. "
                f"Set {MCP_AUTH_PASSWORD_ENV} environment variable."
            )

    # ---------------------------------------------------------------
    # Client management (no DCR -- pre-shared credentials only)
    # ---------------------------------------------------------------

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        """Look up the pre-shared client by ID. Returns None for unknown clients."""
        if not self._client_id or client_id != self._client_id:
            logger.warning(
                f"AUTH_EVENT=client_lookup | client={client_id} | success=False | detail=unknown client_id"
            )
            return None

        # Build a synthetic OAuthClientInformationFull for the pre-shared client
        return OAuthClientInformationFull(
            client_id=self._client_id,
            client_secret=self._client_secret,
            client_id_issued_at=0,
            redirect_uris=[
                "https://claude.ai/api/mcp/auth_callback",
                "https://claude.com/api/mcp/auth_callback",
            ],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="monarch:read monarch:write",
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """DCR is disabled. Always raises an error."""
        logger.warning("Client registration attempted but DCR is disabled")
        raise RegistrationError(error="registration_not_supported")

    # ---------------------------------------------------------------
    # Authorization (password gate)
    # ---------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Start the authorization flow by redirecting to the password gate login page.

        Returns a URL to our /auth/login page with a session ID that maps
        to the stored authorization params.
        """
        # Generate a unique session ID for this authorization attempt
        auth_session_id = secrets.token_urlsafe(32)

        # Store the authorization params for later (when user submits password)
        self._pending_authorizations[auth_session_id] = {
            "client_id": client.client_id,
            "params": params,
            "created_at": time.time(),
        }

        # Clean up expired pending authorizations
        self._cleanup_expired_pending_authorizations()

        # Redirect to our login page
        login_url = f"{self._server_url}/auth/login?session={auth_session_id}"
        logger.info(f"Authorization initiated, redirecting to login page")
        return login_url

    def complete_authorization(self, auth_session_id: str, password: str) -> str:
        """Complete the authorization after the user submits the password.

        Called by the /auth/login POST handler. Returns a redirect URL
        back to the client with an authorization code, or raises on failure.
        """
        # Validate the session
        session = self._pending_authorizations.get(auth_session_id)
        if not session:
            raise ValueError("Invalid or expired authorization session")

        # Check if the session has expired (5 minute window)
        if time.time() - session["created_at"] > AUTH_CODE_LIFETIME:
            del self._pending_authorizations[auth_session_id]
            raise ValueError("Authorization session expired")

        # Validate the password
        if not self._auth_password:
            raise ValueError("Server auth password not configured")

        if not secrets.compare_digest(password, self._auth_password):
            logger.warning(
                "AUTH_EVENT=password_gate | success=False | detail=invalid password"
            )
            raise ValueError("Invalid password")

        params: AuthorizationParams = session["params"]
        client_id: str = session["client_id"]

        # Generate authorization code
        code = secrets.token_urlsafe(48)

        # Store the authorization code
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_LIFETIME,
            resource=params.resource,
        )

        # Clean up the pending authorization
        del self._pending_authorizations[auth_session_id]

        # Build the redirect URL back to the client with the auth code
        redirect_params = {"code": code}
        if params.state:
            redirect_params["state"] = params.state

        redirect_url = construct_redirect_uri(
            str(params.redirect_uri), **redirect_params
        )

        logger.info(
            "AUTH_EVENT=authorization_complete | success=True | detail=auth code issued"
        )
        return redirect_url

    # ---------------------------------------------------------------
    # Token exchange
    # ---------------------------------------------------------------

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> Optional[AuthorizationCode]:
        """Load a stored authorization code."""
        code_obj = self._auth_codes.get(authorization_code)
        if not code_obj:
            return None

        # Check if it belongs to this client
        if code_obj.client_id != client.client_id:
            logger.warning("Authorization code client_id mismatch")
            return None

        # Check expiry
        if code_obj.expires_at and time.time() > code_obj.expires_at:
            del self._auth_codes[authorization_code]
            logger.info("Authorization code expired")
            return None

        return code_obj

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Exchange an authorization code for access + refresh tokens."""
        # Remove the used auth code (one-time use)
        self._auth_codes.pop(authorization_code.code, None)

        # Generate tokens
        access_token_str = secrets.token_urlsafe(48)
        refresh_token_str = secrets.token_urlsafe(48)

        now = time.time()

        # Store access token
        self._access_tokens[access_token_str] = AccessToken(
            token=access_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes or [],
            expires_at=int(now + ACCESS_TOKEN_LIFETIME),
            resource=authorization_code.resource,
        )

        # Store refresh token
        self._refresh_tokens[refresh_token_str] = RefreshToken(
            token=refresh_token_str,
            client_id=client.client_id,
            scopes=authorization_code.scopes or [],
            expires_at=int(now + REFRESH_TOKEN_LIFETIME),
        )

        logger.info(
            "AUTH_EVENT=token_exchange | success=True | detail=access+refresh tokens issued"
        )

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_LIFETIME,
            scope=" ".join(authorization_code.scopes)
            if authorization_code.scopes
            else None,
            refresh_token=refresh_token_str,
        )

    # ---------------------------------------------------------------
    # Refresh tokens
    # ---------------------------------------------------------------

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> Optional[RefreshToken]:
        """Load a stored refresh token."""
        token_obj = self._refresh_tokens.get(refresh_token)
        if not token_obj:
            return None

        # Check client ownership
        if token_obj.client_id != client.client_id:
            logger.warning("Refresh token client_id mismatch")
            return None

        # Check expiry
        if token_obj.expires_at and time.time() > token_obj.expires_at:
            del self._refresh_tokens[refresh_token]
            logger.info("Refresh token expired")
            return None

        return token_obj

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange a refresh token for a new access + refresh token pair (rotation)."""
        # Revoke the old refresh token (rotation)
        self._refresh_tokens.pop(refresh_token.token, None)

        # Generate new tokens
        new_access_token_str = secrets.token_urlsafe(48)
        new_refresh_token_str = secrets.token_urlsafe(48)

        now = time.time()
        effective_scopes = scopes or refresh_token.scopes or []

        # Store new access token
        self._access_tokens[new_access_token_str] = AccessToken(
            token=new_access_token_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(now + ACCESS_TOKEN_LIFETIME),
        )

        # Store new refresh token
        self._refresh_tokens[new_refresh_token_str] = RefreshToken(
            token=new_refresh_token_str,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(now + REFRESH_TOKEN_LIFETIME),
        )

        logger.info(
            "AUTH_EVENT=token_refresh | success=True | detail=rotated to new tokens"
        )

        return OAuthToken(
            access_token=new_access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_LIFETIME,
            scope=" ".join(effective_scopes) if effective_scopes else None,
            refresh_token=new_refresh_token_str,
        )

    # ---------------------------------------------------------------
    # Access token validation (called on every MCP request)
    # ---------------------------------------------------------------

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Validate an access token. Called by the SDK middleware on every request."""
        token_obj = self._access_tokens.get(token)
        if not token_obj:
            return None

        # Check expiry
        if token_obj.expires_at and time.time() > token_obj.expires_at:
            del self._access_tokens[token]
            return None

        return token_obj

    # ---------------------------------------------------------------
    # Token revocation
    # ---------------------------------------------------------------

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke an access or refresh token."""
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
            logger.info("Access token revoked")
        elif isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
            logger.info("Refresh token revoked")

    # ---------------------------------------------------------------
    # Housekeeping
    # ---------------------------------------------------------------

    def _cleanup_expired_pending_authorizations(self) -> None:
        """Remove expired pending authorization sessions."""
        now = time.time()
        expired = [
            sid
            for sid, session in self._pending_authorizations.items()
            if now - session["created_at"] > AUTH_CODE_LIFETIME
        ]
        for sid in expired:
            del self._pending_authorizations[sid]
