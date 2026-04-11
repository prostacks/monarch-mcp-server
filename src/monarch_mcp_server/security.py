"""
Security hardening middleware and utilities for the Monarch MCP Server.

Provides:
- Rate limiting for auth and admin endpoints
- Origin validation to prevent DNS rebinding
- Auth event logging utilities
"""

import logging
import os
import time
from collections import defaultdict
from functools import wraps
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.

    Tracks request counts per IP per endpoint within a configurable window.
    Designed for a single-user server -- no need for Redis/external store.
    """

    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key: (ip, path) -> list of timestamps
        self._requests: dict[tuple[str, str], list[float]] = defaultdict(list)

    def is_rate_limited(self, client_ip: str, path: str) -> bool:
        """Check if a request should be rate limited."""
        key = (client_ip, path)
        now = time.time()
        cutoff = now - self.window_seconds

        # Remove expired entries
        self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            logger.warning(
                f"Rate limit exceeded: {client_ip} on {path} "
                f"({len(self._requests[key])}/{self.max_requests} in {self.window_seconds}s)"
            )
            return True

        self._requests[key].append(now)
        return False

    def cleanup(self) -> None:
        """Remove all expired entries. Call periodically to prevent memory growth."""
        now = time.time()
        cutoff = now - self.window_seconds
        expired_keys = [
            key
            for key, timestamps in self._requests.items()
            if all(ts <= cutoff for ts in timestamps)
        ]
        for key in expired_keys:
            del self._requests[key]


# Global rate limiters with sensible defaults for a single-user server
# Auth endpoints: more restrictive (brute force protection)
auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
# Admin endpoints: moderate (re-auth shouldn't be frequent)
admin_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For from Railway's proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first IP (client) from the chain
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit(
    limiter: RateLimiter,
) -> Callable:
    """Decorator that applies rate limiting to a Starlette route handler."""

    def decorator(
        func: Callable[[Request], Awaitable[Response]],
    ) -> Callable[[Request], Awaitable[Response]]:
        @wraps(func)
        async def wrapper(request: Request) -> Response:
            client_ip = get_client_ip(request)
            path = request.url.path

            if limiter.is_rate_limited(client_ip, path):
                return JSONResponse(
                    {"error": "Too many requests. Please try again later."},
                    status_code=429,
                    headers={"Retry-After": str(limiter.window_seconds)},
                )
            return await func(request)

        return wrapper

    return decorator


# ---------------------------------------------------------------
# Origin Validation ASGI Middleware
# ---------------------------------------------------------------


class OriginValidationMiddleware:
    """ASGI middleware to validate Origin/Referer headers on state-changing requests.

    Prevents DNS rebinding and CSRF attacks. Only applied to POST/PUT/PATCH/DELETE.
    GET requests and requests without Origin headers (e.g., direct API calls) are allowed.
    """

    # Well-known Anthropic origins for claude.ai
    ANTHROPIC_ORIGINS = {
        "https://claude.ai",
        "https://www.claude.ai",
    }

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._allowed_origins: set[str] | None = None

    @property
    def allowed_origins(self) -> set[str]:
        """Lazily compute allowed origins from MCP_SERVER_URL + Anthropic origins."""
        if self._allowed_origins is None:
            origins = set(self.ANTHROPIC_ORIGINS)
            server_url = os.environ.get("MCP_SERVER_URL", "")
            if server_url:
                # Extract origin (scheme + host) from full URL
                from urllib.parse import urlparse

                parsed = urlparse(server_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                origins.add(origin)
            # Also allow localhost for development
            origins.add("http://localhost:8000")
            origins.add("http://127.0.0.1:8000")
            self._allowed_origins = origins
            logger.info(f"Origin validation configured for: {origins}")
        return self._allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # Only validate Origin on state-changing methods
        if method not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return

        # Extract Origin header from scope
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("utf-8", errors="ignore")

        # If no Origin header, allow the request (server-to-server calls,
        # CLI tools, etc. don't send Origin). The MCP SDK's Bearer token
        # auth already protects the /mcp endpoint.
        if not origin:
            await self.app(scope, receive, send)
            return

        # Validate Origin against allowlist
        if origin not in self.allowed_origins:
            logger.warning(f"Rejected request with invalid origin: {origin}")
            response = JSONResponse(
                {"error": "Invalid origin"},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# ---------------------------------------------------------------
# Auth Event Logging
# ---------------------------------------------------------------


def log_auth_event(
    event: str,
    *,
    client_ip: str = "unknown",
    client_id: str = "",
    success: bool = True,
    details: str = "",
) -> None:
    """Log a security-relevant authentication event.

    Events are logged at INFO (success) or WARNING (failure) level
    for easy monitoring via Railway logs.
    """
    level = logging.INFO if success else logging.WARNING
    parts = [f"AUTH_EVENT={event}"]
    if client_ip:
        parts.append(f"ip={client_ip}")
    if client_id:
        parts.append(f"client={client_id}")
    parts.append(f"success={success}")
    if details:
        parts.append(f"detail={details}")
    logger.log(level, " | ".join(parts))
