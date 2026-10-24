"""The declared connector and the one function that serves it.

A connector package declares its fleet name once, as the single entry point of
the ``agent_connector_sdk.connector`` group, and names a :class:`Connector`
value::

    [project.entry-points."agent_connector_sdk.connector"]
    searxng-mcp = "searxng_mcp:connector"

    # searxng_mcp/__init__.py
    from agent_connector_sdk.connector import Connector
    from searxng_mcp.api_client import Api
    from searxng_mcp.auth import get_client

    connector = Connector(api=Api, get_client=get_client, instructions="...")

:func:`run` resolves that declaration and serves the connector: transport
flags, authentication, health, middleware, fleet registration and the package's
skills, prompts, ontology, shapes and ``connector://resources`` all come from
the SDK (SDK-CONNECTOR-CONTROL-R019.1). The package holds no server bootstrap,
no ``__version__`` and no ``__main__`` logic.

Content is found by convention under the package named by the entry point:
``skills/``, ``prompts/``, ``ontology/``, ``connectors/`` and
``connector_sources`` (SDK-CONNECTOR-CONTROL-R071.1). No provider entry points
are needed.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any

from agent_connector_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    ConnectorIdentityError,
    connector_point,
    connector_version,
)

__all__ = [
    "Connector",
    "ConnectorContentDirs",
    "ResolvedConnector",
    "build_server",
    "content_dirs",
    "installed_connectors",
    "resolve_connector",
    "run",
]


@dataclass(frozen=True)
class Connector:
    """What a connector declares beyond its name: its client and its tools.

    Args:
        instructions: Server instructions for models.
        api: The client class; one MCP tool is registered per public method.
        get_client: Per-call client factory (a FastMCP dependency).
        tools: The module (or dotted name) holding the connector's own
            ``register_<tag>_tools`` functions. Defaults to ``<package>.tools``
            when that module exists.
        extra_registrations: Callables run with the FastMCP server after the
            tool surface registers, for registrations the SDK does not own.
        transports: Offered transports; defaults to every SDK transport.
        tool_prefix: Operation-tool name prefix; defaults to one derived from
            the fleet name.
        verbose_targets: Extra ``{client_cls, get_client, prefix?, manifest?,
            result_coercer?}`` operation-tool sources.
        verbose_register: Callable run last to register further tools.
        result_coercer: Coerces each operation result.
        action_dispatch: Keep action-routed tools whole instead of splitting.
    """

    instructions: str = ""
    api: type | None = None
    get_client: Callable[..., Any] | None = None
    tools: ModuleType | str | None = None
    extra_registrations: tuple[Callable[[Any], None], ...] = ()
    transports: Sequence[str] | None = None
    tool_prefix: str | None = None
    verbose_targets: tuple[dict[str, Any], ...] = ()
    verbose_register: Callable[[Any], None] | None = None
    result_coercer: Callable[[Any], Any] | None = None
    action_dispatch: bool = False

    def __post_init__(self) -> None:
        if (self.api is None) != (self.get_client is None):
            raise ValueError("api and get_client are declared together or not at all")


@dataclass(frozen=True)
class ConnectorContentDirs:
    """Where a connector's content lives, by convention under its package."""

    root: Path
    skills: Path
    prompts: Path
    ontology: Path
    connectors: Path


@dataclass(frozen=True)
class ResolvedConnector:
    """A connector declaration joined to its identity, version and location."""

    name: str
    package: str
    distribution: str
    version: str
    connector: Connector
    dirs: ConnectorContentDirs


def content_dirs(package: str) -> ConnectorContentDirs:
    """The conventional content directories of ``package``."""
    spec = importlib.util.find_spec(package.split(".", 1)[0])
    locations = list(spec.submodule_search_locations or []) if spec else []
    if not locations:
        raise ConnectorIdentityError(f"{package!r} is not an importable package")
    root = Path(locations[0])
    return ConnectorContentDirs(
        root=root,
        skills=root / "skills",
        prompts=root / "prompts",
        ontology=root / "ontology",
        connectors=root / "connectors",
    )


def resolve_connector(package: str) -> ResolvedConnector:
    """Resolve ``package``'s declared connector.

    A bare package value declares a content-only connector (``Connector()``);
    ``package:attribute`` names the :class:`Connector` value.

    Raises:
        ConnectorIdentityError: no or several declarations, an invalid name, or
            an attribute that is not a :class:`Connector`.
    """
    point = connector_point(package)
    value: Connector = Connector()
    if point.attribute is not None:
        loaded = getattr(importlib.import_module(point.package), point.attribute, None)
        if not isinstance(loaded, Connector):
            raise ConnectorIdentityError(
                f"{point.package}:{point.attribute} must be an "
                "agent_connector_sdk.connector.Connector"
            )
        value = loaded
    return ResolvedConnector(
        name=point.name,
        package=point.package,
        distribution=point.distribution,
        version=connector_version(point.package),
        connector=value,
        dirs=content_dirs(point.package),
    )


def installed_connectors() -> list[ResolvedConnector]:
    """Every connector declared by an installed distribution, by fleet name."""
    packages = sorted(
        {
            point.value.split(":", 1)[0].strip().split(".", 1)[0]
            for point in entry_points(group=CONNECTOR_ENTRY_POINT_GROUP)
        }
    )
    return sorted((resolve_connector(p) for p in packages), key=lambda r: r.name)


def _tools_module(resolved: ResolvedConnector) -> ModuleType | None:
    tools = resolved.connector.tools
    if isinstance(tools, ModuleType):
        return tools
    if isinstance(tools, str):
        return importlib.import_module(tools)
    name = f"{resolved.package}.tools"
    try:
        found = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        found = None
    return importlib.import_module(name) if found else None


def build_server(
    package: str, *, command_args: list[str] | None = None
) -> tuple[Any, Any]:
    """Build the connector's FastMCP server; return ``(args, mcp)``.

    Raises:
        SystemExit: on ``--help``, a bad flag value or unsafe exposure.
    """
    from agent_connector_sdk.mcp.content import ConnectorContent
    from agent_connector_sdk.mcp.parser import TRANSPORTS
    from agent_connector_sdk.mcp.server import create_mcp_server
    from agent_connector_sdk.mcp.tool_surface import register_tool_surface

    resolved = resolve_connector(package)
    connector = resolved.connector
    args, mcp, middlewares = create_mcp_server(
        resolved.name,
        version=resolved.version,
        instructions=connector.instructions,
        command_args=command_args,
        transport_choices=tuple(connector.transports or TRANSPORTS),
        content=ConnectorContent(
            connector=resolved.name,
            package_root=resolved.dirs.root,
            package_version=resolved.version,
        ),
    )
    register_tool_surface(
        mcp,
        service=resolved.name,
        client_cls=connector.api,
        get_client=connector.get_client,
        tools_module=_tools_module(resolved),
        package_root=resolved.dirs.root,
        tool_prefix=connector.tool_prefix,
        verbose_targets=list(connector.verbose_targets) or None,
        verbose_register=connector.verbose_register,
        result_coercer=connector.result_coercer,
        action_dispatch=connector.action_dispatch,
    )
    for register in connector.extra_registrations:
        register(mcp)
    for middleware in middlewares:
        mcp.add_middleware(middleware)
    return args, mcp


def _calling_package() -> str:
    frame: Any = sys._getframe(2)
    while frame is not None:
        module = str(frame.f_globals.get("__name__", ""))
        if module == "__main__":
            module = str(frame.f_globals.get("__package__") or "")
        if module and module.split(".", 1)[0] != "agent_connector_sdk":
            return module.split(".", 1)[0]
        frame = frame.f_back
    raise ConnectorIdentityError("run() cannot infer the connector package; pass it")


def run(package: str | None = None, *, command_args: list[str] | None = None) -> None:
    """Serve the connector declared by ``package`` until the transport ends.

    ``package`` defaults to the package of the caller, so ``python -m <pkg>``
    is ``from agent_connector_sdk import run; run()``.
    """
    name = package or _calling_package()
    args, mcp = build_server(name, command_args=command_args)
    resolved = resolve_connector(name)
    print(f"{resolved.name} MCP v{resolved.version}", file=sys.stderr)
    print("\nStarting MCP Server", file=sys.stderr)
    print(f"  Transport: {args.transport.upper()}", file=sys.stderr)
    print(f"  Auth: {args.auth_type}", file=sys.stderr)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport in ("streamable-http", "sse"):
        mcp.run(transport=args.transport, host=args.host, port=args.port)
    else:
        print(f"Invalid transport: {args.transport}", file=sys.stderr)
        raise SystemExit(1)
