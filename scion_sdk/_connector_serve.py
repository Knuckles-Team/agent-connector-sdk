"""Build and serve the FastMCP server of a declared connector."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

from scion_sdk._connector_decl import ResolvedConnector, resolve_connector
from scion_sdk.connector_hooks import (
    RegistrationContext,
    serve_readiness,
    serve_routes,
)
from scion_sdk.connector_identity import ConnectorIdentityError

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _tools_module(resolved: ResolvedConnector) -> ModuleType | None:
    if resolved.connector.tool_registry:
        return None
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
    from scion_sdk.config import load_config
    from scion_sdk.mcp.content import ConnectorContent
    from scion_sdk.mcp.parser import TRANSPORTS
    from scion_sdk.mcp.server import create_mcp_server
    from scion_sdk.mcp.tool_surface import (
        register_action_tools,
        register_tool_surface,
    )

    load_config()
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
            package_root=resolved.dirs.content,
            package_version=resolved.version,
        ),
    )
    for tool in connector.inline_tools:
        mcp.add_tool(tool)
    register_tool_surface(
        mcp,
        service=resolved.name,
        client_cls=connector.api,
        get_client=connector.get_client,
        tool_registry=list(connector.tool_registry) or None,
        tools_module=_tools_module(resolved),
        package_root=resolved.dirs.root,
        tool_prefix=connector.tool_prefix,
        verbose_targets=list(connector.verbose_targets) or None,
        verbose_register=connector.verbose_register,
        result_coercer=connector.result_coercer,
        action_dispatch=connector.action_dispatch,
    )
    if connector.action_tools:
        register_action_tools(
            mcp, connector.action_tools, prefixes=connector.action_prefixes
        )
    _serve_hooks(mcp, args, resolved)
    for middleware in middlewares:
        mcp.add_middleware(middleware)
    return args, mcp


def _serve_hooks(mcp: FastMCP[Any], args: Any, resolved: ResolvedConnector) -> None:
    connector = resolved.connector
    context = RegistrationContext(
        server=mcp,
        name=resolved.name,
        version=resolved.version,
        settings=args,
        client_factory=connector.get_client,
        auth=mcp.auth,
    )
    for register in connector.extra_registrations:
        register(context)
    serve_routes(mcp, connector.routes)
    if connector.readiness is not None:
        serve_readiness(mcp, connector.readiness)


def _calling_package() -> str:
    frame: Any = sys._getframe(2)
    while frame is not None:
        module = str(frame.f_globals.get("__name__", ""))
        if module == "__main__":
            module = str(frame.f_globals.get("__package__") or "")
        if module and module.split(".", 1)[0] != "scion_sdk":
            return module.split(".", 1)[0]
        frame = frame.f_back
    raise ConnectorIdentityError("run() cannot infer the connector package; pass it")


def run(package: str | None = None, *, command_args: list[str] | None = None) -> None:
    """Serve the connector declared by ``package`` until the transport ends.

    ``package`` defaults to the package of the caller, so ``python -m <pkg>``
    is ``from scion_sdk import run; run()``.
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
