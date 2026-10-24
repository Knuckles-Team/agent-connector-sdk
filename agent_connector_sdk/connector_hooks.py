"""Typed bootstrap hooks a :class:`~agent_connector_sdk.connector.Connector` declares.

A connector whose server did more than the plain bootstrap declares what it did
as data on its ``Connector`` value, and ``build_server`` applies it through
fastmcp's own registration API (SDK-CONNECTOR-CONTROL-R019.2):

- ``tool_registry``: explicit ``(tag, toggle_setting, registrar)`` entries, for
  registrars whose tag or toggle is not derived from a ``register_<tag>_tools``
  name;
- ``action_tools`` / ``action_prefixes``: registrars whose action-routed tools
  are always served one typed tool per action, named ``<prefix>_<action>``;
- ``inline_tools``: tool functions (or fastmcp ``Tool`` values) added with
  ``FastMCP.add_tool``;
- ``routes``: extra HTTP routes added with ``FastMCP.custom_route``;
- ``readiness``: a backend probe served at ``/ready`` beside the SDK's
  liveness-only ``/health``;
- ``extra_registrations``: callables that receive a :class:`RegistrationContext`;
- ``content_root``: a package-relative content directory for a package whose
  content does not sit at its root.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from fastmcp.server.auth import AuthProvider
    from fastmcp.tools import Tool
    from starlette.requests import Request
    from starlette.responses import Response

__all__ = [
    "READINESS_PATH",
    "RESERVED_PATHS",
    "InlineTool",
    "Readiness",
    "ReadinessProbe",
    "ReadinessValue",
    "Registration",
    "RegistrationContext",
    "Route",
    "ServerRegistrar",
    "ToolRegistryEntry",
    "content_subdir",
    "serve_readiness",
    "serve_routes",
]

_logger = logging.getLogger(__name__)

#: The path the declared readiness probe answers on.
READINESS_PATH = "/ready"
#: Paths the SDK serves itself; a declared route never replaces one.
RESERVED_PATHS = frozenset({"/health", READINESS_PATH})

#: A registrar that adds tools to the server it is given.
type ServerRegistrar = Callable[[FastMCP[object]], object]
#: ``(tag, toggle_setting, registrar)``: the registrar runs unless the setting is false.
type ToolRegistryEntry = tuple[str, str, ServerRegistrar]
#: A tool function (optionally decorated with ``fastmcp.tools.tool``) or a fastmcp ``Tool``.
type InlineTool = Tool | Callable[..., object]
#: A JSON value a readiness detail may carry.
type ReadinessValue = str | int | float | bool | None


@dataclass(frozen=True)
class RegistrationContext:
    """What a registration callable receives: the server and the shared state.

    Args:
        server: The connector's FastMCP server.
        name: The connector's fleet name.
        version: The connector's version from package metadata.
        settings: The parsed server settings (transport, host, port, auth
            flags and their environment defaults).
        client_factory: The declared per-call client factory, or ``None``.
        auth: The server's authentication provider, or ``None``.
    """

    server: FastMCP[object]
    name: str
    version: str
    settings: argparse.Namespace
    client_factory: Callable[..., object] | None
    auth: AuthProvider | None


#: A registration callable run with the :class:`RegistrationContext`.
type Registration = Callable[[RegistrationContext], None]


@dataclass(frozen=True)
class Readiness:
    """The result of a readiness probe.

    Args:
        ready: Whether the backend answers; ``False`` serves HTTP 503.
        detail: Extra JSON fields for the response body. Never put a secret
            or an exception message here.
    """

    ready: bool
    detail: Mapping[str, ReadinessValue] = field(default_factory=dict)


#: An async backend probe; an exception it raises is served as not ready.
type ReadinessProbe = Callable[[], Awaitable[Readiness]]


@dataclass(frozen=True)
class Route:
    """One extra HTTP route, added with ``FastMCP.custom_route``.

    Args:
        path: The absolute route path; never ``/health`` or ``/ready``.
        handler: The async Starlette handler.
        methods: The HTTP methods it answers.
        name: The optional route name.
    """

    path: str
    handler: Callable[[Request], Awaitable[Response]]
    methods: tuple[str, ...] = ("GET",)
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"route path {self.path!r} must start with '/'")
        if self.path.rstrip("/") in RESERVED_PATHS:
            raise ValueError(
                f"route path {self.path!r} is served by the SDK; declare readiness instead"
            )
        if not self.methods:
            raise ValueError(f"route {self.path!r} declares no methods")


def serve_routes(server: FastMCP[object], routes: tuple[Route, ...]) -> None:
    """Add each declared route; two routes on one path and method are refused."""
    seen: set[tuple[str, str]] = set()
    for route in routes:
        for method in route.methods:
            key = (route.path, method.upper())
            if key in seen:
                raise ValueError(
                    f"route {method.upper()} {route.path} is declared twice"
                )
            seen.add(key)
        server.custom_route(route.path, methods=list(route.methods), name=route.name)(
            route.handler
        )


def serve_readiness(server: FastMCP[object], probe: ReadinessProbe) -> None:
    """Serve ``probe`` at :data:`READINESS_PATH`: 200 when ready, 503 otherwise."""
    from starlette.responses import JSONResponse

    async def ready(_request: Request) -> Response:
        try:
            result = await probe()
        except Exception as exc:
            _logger.warning("readiness probe failed", exc_info=exc)
            body: dict[str, ReadinessValue] = {
                "status": "unavailable",
                "error": type(exc).__name__,
            }
            return JSONResponse(
                body, status_code=503, headers={"Cache-Control": "no-store"}
            )
        status = "ready" if result.ready else "unavailable"
        return JSONResponse(
            {**result.detail, "status": status},
            status_code=200 if result.ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    server.custom_route(READINESS_PATH, methods=["GET"])(ready)


def content_subdir(content_root: str) -> PurePosixPath:
    """Validate a package-relative content directory.

    Raises:
        ValueError: an empty, absolute or escaping path.
    """
    path = PurePosixPath(content_root)
    if not content_root.strip() or path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"content_root {content_root!r} must be a relative path inside the package"
        )
    return path
