"""
Secure session management for Monarch Money MCP Server.

Token resolution hierarchy (highest priority first):
1. In-memory override (set at runtime via admin re-auth flow)
2. MONARCH_TOKEN environment variable (for remote/container deployments)
3. System keyring (for local/stdio mode)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from monarchmoney import MonarchMoney

logger = logging.getLogger(__name__)

# Environment variable name for remote token storage
MONARCH_TOKEN_ENV = "MONARCH_TOKEN"

# Keyring service identifiers
KEYRING_SERVICE = "com.mcp.monarch-mcp-server"
KEYRING_USERNAME = "monarch-token"


def _keyring_available() -> bool:
    """Check if keyring is available and functional."""
    try:
        import keyring as kr

        # Some environments have keyring installed but no working backend
        # (e.g., containers without a desktop session). Probe with a test read.
        kr.get_password(KEYRING_SERVICE, "__probe__")
        return True
    except Exception:
        return False


class SecureMonarchSession:
    """Manages Monarch Money sessions using in-memory, env var, or keyring storage.

    Token resolution hierarchy (highest priority first):
    1. In-memory override (set at runtime via update_token_in_memory)
    2. MONARCH_TOKEN environment variable
    3. System keyring (when available)
    """

    def __init__(self) -> None:
        self._in_memory_token: Optional[str] = None
        self._token_updated_at: Optional[datetime] = None
        self._keyring_available: Optional[bool] = None  # lazy-checked

    @property
    def keyring_available(self) -> bool:
        """Lazily check if keyring is available."""
        if self._keyring_available is None:
            self._keyring_available = _keyring_available()
            if self._keyring_available:
                logger.info("Keyring backend available")
            else:
                logger.info(
                    "Keyring backend not available, using env var / in-memory fallback"
                )
        return self._keyring_available

    @property
    def token_updated_at(self) -> Optional[datetime]:
        """Timestamp of the last in-memory token update."""
        return self._token_updated_at

    def update_token_in_memory(self, token: str) -> None:
        """Store a token in memory (highest priority). Used by the admin re-auth flow.

        This does NOT persist to keyring or env var -- it only lives for the
        lifetime of the server process. On Railway, the token survives until
        the next deploy/restart.
        """
        self._in_memory_token = token
        self._token_updated_at = datetime.now(timezone.utc)
        logger.info("Token updated in memory (runtime override)")

    def save_token(self, token: str) -> None:
        """Save the authentication token to the best available storage.

        - If keyring is available: saves to keyring (local/stdio mode).
        - Always updates the in-memory override so the token is immediately usable.
        """
        # Always update in-memory so the token is available immediately
        self.update_token_in_memory(token)

        if self.keyring_available:
            try:
                import keyring as kr

                kr.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
                logger.info("Token saved to keyring")
                self._cleanup_old_session_files()
            except Exception as e:
                logger.error(f"Failed to save token to keyring: {e}")
                raise
        else:
            logger.info("Token saved in memory only (no keyring available)")

    def load_token(self) -> Optional[str]:
        """Load the authentication token using the priority hierarchy.

        Resolution order:
        1. In-memory override
        2. MONARCH_TOKEN environment variable
        3. System keyring
        """
        # 1. In-memory override (highest priority)
        if self._in_memory_token:
            logger.debug("Token loaded from in-memory override")
            return self._in_memory_token

        # 2. Environment variable
        env_token = os.environ.get(MONARCH_TOKEN_ENV)
        if env_token:
            logger.info("Token loaded from MONARCH_TOKEN environment variable")
            return env_token

        # 3. System keyring (lowest priority)
        if self.keyring_available:
            try:
                import keyring as kr

                token = kr.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
                if token:
                    logger.info("Token loaded from keyring")
                    return token
                else:
                    logger.info("No token found in keyring")
            except Exception as e:
                logger.error(f"Failed to load token from keyring: {e}")

        logger.info("No token found in any storage")
        return None

    def delete_token(self) -> None:
        """Delete the authentication token from all storage layers."""
        # Clear in-memory
        self._in_memory_token = None
        self._token_updated_at = None

        # Clear keyring if available
        if self.keyring_available:
            try:
                import keyring as kr

                kr.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
                logger.info("Token deleted from keyring")
                self._cleanup_old_session_files()
            except Exception as e:
                # keyring.errors.PasswordDeleteError or similar
                if "PasswordDeleteError" in type(e).__name__:
                    logger.info("No token found in keyring to delete")
                else:
                    logger.error(f"Failed to delete token from keyring: {e}")

        logger.info("Token cleared from all storage")

    def get_authenticated_client(self) -> Optional[MonarchMoney]:
        """Get an authenticated MonarchMoney client."""
        token = self.load_token()
        if not token:
            return None

        try:
            client = MonarchMoney(token=token)
            logger.info("MonarchMoney client created with stored token")
            return client
        except Exception as e:
            logger.error(f"Failed to create MonarchMoney client: {e}")
            return None

    def save_authenticated_session(self, mm: MonarchMoney) -> None:
        """Save the session from an authenticated MonarchMoney instance."""
        if mm.token:
            self.save_token(mm.token)
        else:
            logger.warning("MonarchMoney instance has no token to save")

    def get_token_status(self) -> dict:
        """Return a status summary of token availability across all storage layers.

        Useful for the admin status page and debugging.
        """
        status = {
            "has_in_memory_token": self._in_memory_token is not None,
            "in_memory_updated_at": self._token_updated_at.isoformat()
            if self._token_updated_at
            else None,
            "has_env_var_token": bool(os.environ.get(MONARCH_TOKEN_ENV)),
            "keyring_available": self.keyring_available,
            "has_keyring_token": False,
            "has_any_token": False,
        }

        if self.keyring_available:
            try:
                import keyring as kr

                status["has_keyring_token"] = (
                    kr.get_password(KEYRING_SERVICE, KEYRING_USERNAME) is not None
                )
            except Exception:
                pass

        status["has_any_token"] = (
            status["has_in_memory_token"]
            or status["has_env_var_token"]
            or status["has_keyring_token"]
        )

        return status

    def _cleanup_old_session_files(self) -> None:
        """Clean up old insecure session files."""
        cleanup_paths = [
            ".mm/mm_session.pickle",
            "monarch_session.json",
            ".mm",  # Remove the entire directory if empty
        ]

        for path in cleanup_paths:
            try:
                if os.path.exists(path):
                    if os.path.isfile(path):
                        os.remove(path)
                        logger.info(f"Cleaned up old insecure session file: {path}")
                    elif os.path.isdir(path) and not os.listdir(path):
                        os.rmdir(path)
                        logger.info(f"Cleaned up empty session directory: {path}")
            except Exception as e:
                logger.warning(f"Could not clean up {path}: {e}")


# Global session manager instance
secure_session = SecureMonarchSession()
