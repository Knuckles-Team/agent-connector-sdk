"""Create a connector MCP server with the fleet's standard policy.

Extracted from ``agent_utilities.mcp.server_factory.create_mcp_server``. It keeps
the fleet-facing contract (``create_mcp_server`` returns
``(args, mcp, middlewares)``; the same flags and environment defaults; fail
closed for exposed listeners) and leaves AU-internal wiring behind: the
WorkItem tasks extension, engine-backed ``/metrics``, semantic tool filtering
through the knowledge graph, and delegation and Eunomia middleware.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_connector_sdk.config import setting
from agent_connector_sdk.credentials.resolver import CredentialResolver
from agent_connector_sdk.mcp.auth.factory import configure_auth
from agent_connector_sdk.mcp.auth.policy import AuthConfigurationError
from agent_connector_sdk.mcp.content import ConnectorContent, register_connector_content
from agent_connector_sdk.mcp.exposure import (
    NetworkExposureError,
    validate_network_exposure,
)
from agent_connector_sdk.mcp.middleware import build_middleware
from agent_connector_sdk.mcp.parser import TRANSPORTS, create_mcp_parser
from agent_connector_sdk.mcp.registry import (
    ServerRegistry,
    endpoint_reference,
    lease_ttl_seconds,
    registration_lifespan,
)
from agent_connector_sdk.mcp.visibility import VisibilityTransform
from agent_connector_sdk.mcp.visibility_policy import VisibilityPolicy

__all__ = ["create_mcp_server"]

_logger = logging.getLogger(__name__)


def _parse_arguments(
    parser: argparse.ArgumentParser, command_args: list[str] | None
) -> argparse.Namespace:
    args, _ = parser.parse_known_args(command_args)
    if args.help:
        parser.print_help(sys.stderr)
        raise SystemExit(0)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    return args


def _authentication(
    args: argparse.Namespace, resolver: CredentialResolver | None
) -> Any:
    try:
        validate_network_exposure(args)
        return configure_auth(args, resolver=resolver)
    except (NetworkExposureError, AuthConfigurationError) as exc:
        _logger.error("Refusing to build MCP server: %s", exc)
        raise SystemExit(1) from exc


def _lifespan(
    args: argparse.Namespace, *, name: str, registry: ServerRegistry | None
) -> Callable[[Any], AbstractAsyncContextManager[None]] | None:
    if registry is None or not setting("MCP_FLEET_REGISTRATION", True):
        return None
    url = endpoint_reference(
        name, transport=args.transport, host=args.host, port=args.port
    )
    return registration_lifespan(
        registry, name=name, url=url, ttl_secs=lease_ttl_seconds()
    )


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


def create_mcp_server(
    name: str,
    *,
    version: str,
    instructions: str = "",
    command_args: list[str] | None = None,
    transport_choices: Sequence[str] = TRANSPORTS,
    content: ConnectorContent | None = None,
    server_registry: ServerRegistry | None = None,
    credential_resolver: CredentialResolver | None = None,
) -> tuple[argparse.Namespace, FastMCP[Any], list[Any]]:
    """Build a connector FastMCP server.

    Args:
        name: Server name reported to clients and registered with the fleet.
        version: Server version reported to clients.
        instructions: Server instructions for models.
        command_args: Arguments to parse instead of ``sys.argv``.
        transport_choices: Transports this server offers.
        content: Connector content to serve as MCP primitives.
        server_registry: Registry to renew this server's lease in; the lease
            runs only when ``MCP_FLEET_REGISTRATION`` is true (the default).
        credential_resolver: Resolver for secret references in auth flags.

    Returns:
        ``(args, mcp, middlewares)``; the caller adds the middlewares.

    Raises:
        SystemExit: on ``--help``, an invalid port, unsafe network exposure or
            invalid authentication settings.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
    args = _parse_arguments(
        create_mcp_parser(transport_choices=transport_choices), command_args
    )
    mcp: FastMCP[Any] = FastMCP(
        name,
        instructions=instructions,
        version=version,
        auth=_authentication(args, credential_resolver),
        lifespan=_lifespan(args, name=name, registry=server_registry),
    )
    mcp.custom_route("/health", methods=["GET"])(_health)
    mcp.add_transform(
        VisibilityTransform(
            VisibilityPolicy.from_settings(args.tools, args.disabled_tools)
        )
    )
    if content is not None:
        register_connector_content(mcp, content)
    return args, mcp, build_middleware()
