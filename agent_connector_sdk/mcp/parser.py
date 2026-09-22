"""The standard connector server command line.

Extracted from ``agent_utilities.mcp.server_factory.create_mcp_parser``. Every
secret-bearing flag takes a reference (``--*-ref``); references are resolved
when authentication is configured and never appear as values in ``argv``.
Flags for AU-internal features (delegation, Eunomia, OpenAPI import) are not
part of the SDK.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from agent_connector_sdk.config import setting
from agent_connector_sdk.mcp.auth.policy import AUTH_TYPES

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "TRANSPORTS", "create_mcp_parser"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
TRANSPORTS = ("stdio", "streamable-http", "sse")

#: Plain string flags and the setting that supplies each default.
_SETTING_FLAGS: tuple[tuple[tuple[str, ...], str | None], ...] = (
    (("--tls-certfile",), "MCP_TLS_CERTFILE"),
    (("--tls-keyfile",), "MCP_TLS_KEYFILE"),
    (("--trusted-proxy-cidrs",), "MCP_TRUSTED_PROXY_CIDRS"),
    (("--allowed-hosts",), "MCP_ALLOWED_HOSTS"),
    (("--allowed-origins",), "MCP_ALLOWED_ORIGINS"),
    (("--static-tokens-ref",), "FASTMCP_SERVER_AUTH_STATIC_TOKENS_REF"),
    (("--token-jwks-uri",), "FASTMCP_SERVER_AUTH_JWT_JWKS_URI"),
    (("--token-audience",), "FASTMCP_SERVER_AUTH_JWT_AUDIENCE"),
    (("--token-algorithm",), "FASTMCP_SERVER_AUTH_JWT_ALGORITHM"),
    (("--token-secret-ref",), "FASTMCP_SERVER_AUTH_JWT_SECRET_REF"),
    (("--token-public-key",), "FASTMCP_SERVER_AUTH_JWT_PUBLIC_KEY"),
    (("--required-scopes",), "FASTMCP_SERVER_AUTH_JWT_REQUIRED_SCOPES"),
    (("--oauth-upstream-auth-endpoint",), None),
    (("--oauth-upstream-token-endpoint",), None),
    (("--oauth-upstream-client-id",), None),
    (("--oauth-upstream-client-secret-ref",), "OAUTH_UPSTREAM_CLIENT_SECRET_REF"),
    (("--oauth-base-url",), None),
    (("--oidc-config-url",), "OIDC_CONFIG_URL"),
    (("--oidc-client-id",), "OIDC_CLIENT_ID"),
    (("--oidc-client-secret-ref",), "OIDC_CLIENT_SECRET_REF"),
    (("--oidc-base-url",), "OIDC_BASE_URL"),
    (("--public-base-url",), "MCP_PUBLIC_BASE_URL"),
    (("--remote-auth-servers",), None),
    (("--remote-base-url",), None),
    (("--allowed-client-redirect-uris",), None),
    (("--tools", "--toolsets"), "MCP_ENABLED_TOOLS"),
    (("--disabled-tools", "--disabled-toolsets"), "MCP_DISABLED_TOOLS"),
)


def create_mcp_parser(
    *, transport_choices: Sequence[str] = TRANSPORTS
) -> argparse.ArgumentParser:
    """The standard connector server argument parser.

    Raises:
        ValueError: ``transport_choices`` is empty or names an unknown transport.
    """
    if not transport_choices or not set(transport_choices) <= set(TRANSPORTS):
        raise ValueError("transport_choices must be a non-empty subset of TRANSPORTS")
    parser = argparse.ArgumentParser(add_help=False, description="MCP Server")
    parser.add_argument(
        "-t",
        "--transport",
        default=setting("TRANSPORT", "stdio"),
        choices=list(transport_choices),
    )
    _add_typed_flags(parser)
    for flags, key in _SETTING_FLAGS:
        parser.add_argument(*flags, default=setting(key) if key else None)
    return parser


def _add_typed_flags(parser: argparse.ArgumentParser) -> None:
    """Flags with a type, action, choices or composite default."""
    parser.add_argument("-H", "--host", default=setting("HOST", DEFAULT_HOST))
    parser.add_argument("-p", "--port", type=int, default=setting("PORT", DEFAULT_PORT))
    parser.add_argument(
        "--tls-terminated",
        action="store_true",
        default=setting("MCP_TLS_TERMINATED", False),
    )
    parser.add_argument(
        "--auth-type", default=setting("AUTH_TYPE", "none"), choices=list(AUTH_TYPES)
    )
    _add_network_bound_flags(parser)
    parser.add_argument(
        "--token-issuer",
        default=setting("OIDC_ISSUER") or setting("FASTMCP_SERVER_AUTH_JWT_ISSUER"),
    )
    parser.add_argument("--help", action="store_true")


def _add_network_bound_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=setting("MCP_MAX_REQUEST_BYTES"),
    )
    parser.add_argument(
        "--max-connections", type=int, default=setting("MCP_MAX_CONNECTIONS")
    )
    parser.add_argument(
        "--listen-backlog", type=int, default=setting("MCP_LISTEN_BACKLOG")
    )
    parser.add_argument(
        "--keepalive-timeout-seconds",
        type=int,
        default=setting("MCP_KEEPALIVE_TIMEOUT_SECONDS"),
    )
    parser.add_argument(
        "--graceful-shutdown-timeout-seconds",
        type=int,
        default=setting("MCP_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS"),
    )
    parser.add_argument(
        "--request-body-timeout-seconds",
        type=float,
        default=setting("MCP_REQUEST_BODY_TIMEOUT_SECONDS"),
    )
