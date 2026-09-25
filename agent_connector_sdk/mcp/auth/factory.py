"""Select and build the auth provider for ``--auth-type``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

import httpx

from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.mcp.auth.jwt import configure_jwt_auth
from agent_connector_sdk.mcp.auth.policy import (
    AUTH_TYPES,
    AuthConfigurationError,
    AuthInputs,
)
from agent_connector_sdk.mcp.auth.proxies import (
    configure_oauth_proxy,
    configure_oidc_proxy,
    configure_remote_oauth,
)

__all__ = ["configure_auth"]

_BUILDERS: dict[str, Callable[[AuthInputs], Any]] = {
    "jwt": configure_jwt_auth,
    "oauth-proxy": configure_oauth_proxy,
    "oidc-proxy": configure_oidc_proxy,
    "remote-oauth": configure_remote_oauth,
}

#: Removed modes and the replacement each one names in its refusal.
_REMOVED_AUTH_TYPES: dict[str, str] = {
    "static": (
        "static token maps are retired; issue an API key and exchange it at "
        "the Graph OS /oauth/token endpoint (RFC 8693), or use --auth-type jwt "
        "against an OIDC issuer"
    ),
}


def configure_auth(
    args: argparse.Namespace,
    *,
    resolver: CredentialResolver | None = None,
    http_client: httpx.Client | None = None,
) -> Any:
    """Build the FastMCP auth provider for ``args.auth_type``.

    Returns:
        ``None`` for ``none``; otherwise the configured provider.

    Raises:
        AuthConfigurationError: the mode is unknown or its settings are
            incomplete or invalid. An unknown mode never yields an
            unauthenticated server.
    """
    auth_type = str(args.auth_type or "none")
    if auth_type == "none":
        return None
    removed = _REMOVED_AUTH_TYPES.get(auth_type)
    if removed is not None:
        raise AuthConfigurationError(f"auth type {auth_type!r} was removed: {removed}")
    builder = _BUILDERS.get(auth_type)
    if builder is None:
        raise AuthConfigurationError(
            f"unsupported auth type {auth_type!r}; expected one of {', '.join(AUTH_TYPES)}"
        )
    return builder(AuthInputs(args=args, resolver=resolver, http_client=http_client))
