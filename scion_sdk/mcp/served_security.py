"""Fail-closed security profile for a connector's served MCP server.

Ported from ``agent_utilities.security.request_identity.apply_served_security_profile``.
A network MCP transport (``streamable-http``, ``sse``) is a multi-client surface.
When one is served, :func:`apply_served_security_profile`:

* refuses to start unless an authentication provider was actually constructed
  (a populated JWKS variable is not a substitute) and an audience is configured;
* installs :class:`ServedSecurityMiddleware`, which rejects every MCP request that
  lacks a verified identity, a tenant claim, an active session, or the scopes the
  operator requires (``CONNECTOR_REQUIRED_SCOPES``).

``create_mcp_server`` applies it to every server. The only way out is an explicit
:class:`ServedSecurityOverride` with a written reason, which is logged at warning
level. ``stdio`` is a single-client local transport and is left alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.shared.exceptions import MCPError

from scion_sdk.config import csv_values, setting

__all__ = [
    "SERVED_TRANSPORTS",
    "ServedSecurityError",
    "ServedSecurityMiddleware",
    "ServedSecurityOverride",
    "apply_served_security_profile",
]

_logger = logging.getLogger(__name__)

SERVED_TRANSPORTS: frozenset[str] = frozenset({"streamable-http", "sse"})
_TENANT_CLAIMS = ("tenant_id", "tenant", "org_id", "tid", "org")
_DENIED = -32001


class ServedSecurityError(RuntimeError):
    """The served security profile cannot be satisfied; the server must not start."""


@dataclass(frozen=True)
class ServedSecurityOverride:
    """An explicit, logged decision to serve a network transport without the profile."""

    reason: str

    def __post_init__(self) -> None:
        if len(self.reason.strip()) < 8:
            raise ValueError("a served-security override needs a written reason")


def _claims(token: Any) -> dict[str, Any]:
    claims = getattr(token, "claims", None)
    return claims if isinstance(claims, dict) else {}


def _scopes(token: Any) -> set[str]:
    scopes = {str(s) for s in (getattr(token, "scopes", None) or [])}
    claim = _claims(token).get("scope")
    if isinstance(claim, str):
        scopes.update(claim.split())
    return scopes


def _session_id(context: MiddlewareContext[Any]) -> str:
    try:
        return str(context.fastmcp_context.session_id or "")  # type: ignore[union-attr]
    except (AttributeError, RuntimeError):
        return ""


class ServedSecurityMiddleware(Middleware):
    """Reject requests without identity, tenant, session or required scopes."""

    def __init__(self, required_scopes: frozenset[str] = frozenset()) -> None:
        self._required = required_scopes

    def _refusal(self, context: MiddlewareContext[Any]) -> str | None:
        token = get_access_token()
        if token is None:
            return "authenticated identity is required"
        claims = _claims(token)
        if not str(claims.get("sub") or getattr(token, "client_id", "") or "").strip():
            return "the token carries no subject"
        if not any(str(claims.get(key) or "").strip() for key in _TENANT_CLAIMS):
            return "the token carries no tenant"
        if not self._required <= _scopes(token):
            return "the token lacks a required scope"
        if not _session_id(context):
            return "an active session is required"
        return None

    async def on_request(self, context: MiddlewareContext[Any], call_next: Any) -> Any:
        reason = self._refusal(context)
        if reason is not None:
            _logger.warning("served security refused %s: %s", context.method, reason)
            raise MCPError(_DENIED, "access denied")
        return await call_next(context)


def apply_served_security_profile(
    transport: str,
    *,
    auth_provider: Any,
    mcp: Any = None,
    audience: str | None = None,
    override: ServedSecurityOverride | None = None,
) -> bool:
    """Enforce the served profile for a network transport.

    Args:
        transport: The selected MCP transport.
        auth_provider: The constructed FastMCP auth provider, or ``None``.
        mcp: The server to install :class:`ServedSecurityMiddleware` on.
        audience: The configured token audience; ``CONNECTOR_JWT_AUDIENCE`` and
            ``FASTMCP_SERVER_AUTH_JWT_AUDIENCE`` are read when omitted.
        override: An explicit, logged opt-out.

    Returns:
        ``True`` when the profile is active, ``False`` for ``stdio`` or an override.

    Raises:
        ServedSecurityError: a network transport has no auth provider or audience.
    """
    if transport not in SERVED_TRANSPORTS:
        return False
    if override is not None:
        _logger.warning(
            "served security profile OVERRIDDEN over %s: %s",
            transport,
            override.reason,
        )
        return False
    if auth_provider is None:
        raise ServedSecurityError(
            f"Refusing to serve over {transport}: no authentication provider is "
            "configured, so client identity cannot be validated. Set --auth-type "
            "to a real scheme."
        )
    resolved = str(
        audience
        or setting("CONNECTOR_JWT_AUDIENCE")
        or setting("FASTMCP_SERVER_AUTH_JWT_AUDIENCE")
        or ""
    ).strip()
    if not resolved:
        raise ServedSecurityError(
            f"Refusing to serve over {transport}: a token audience is required."
        )
    if mcp is not None:
        required = frozenset(csv_values(setting("CONNECTOR_REQUIRED_SCOPES", "")))
        mcp.add_middleware(ServedSecurityMiddleware(required))
    _logger.warning(
        "served security profile ACTIVE over %s: identity, tenant, ACL and session "
        "are mandatory",
        transport,
    )
    return True
