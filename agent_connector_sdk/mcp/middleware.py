"""The standard connector middleware stack.

Extracted from ``agent_utilities.mcp.server_factory``: privacy-safe error
handling and a per-caller rate limit. Without a caller key, FastMCP's rate limiter
puts every request from every client into one global bucket, so a few clients
handshaking at once starve each other.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

__all__ = ["build_middleware", "caller_bucket", "rate_limit_client_id"]


def caller_bucket(client_id: object, claims: object) -> str:
    """The rate-limit bucket for a caller identity (``anonymous`` when empty)."""
    mapping = claims if isinstance(claims, dict) else {}
    identity = "\x00".join(
        str(value or "")
        for value in (client_id, mapping.get("sub"), mapping.get("tenant_id"))
    )
    if not identity.strip("\x00"):
        return "anonymous"
    digest = hashlib.blake2s(identity.encode("utf-8"), digest_size=16).hexdigest()
    return f"caller_{digest}"


def rate_limit_client_id(_context: Any) -> str:
    """Rate-limit key for the current request's authenticated caller."""
    token = get_access_token()
    if token is None:
        return "anonymous"
    return caller_bucket(token.client_id, token.claims)


def build_middleware() -> list[Any]:
    """Error handling without tracebacks, then 10 requests/s per caller (burst 20)."""
    return [
        ErrorHandlingMiddleware(include_traceback=False, transform_errors=True),
        RateLimitingMiddleware(
            max_requests_per_second=10.0,
            burst_capacity=20,
            get_client_id=rate_limit_client_id,
        ),
    ]
