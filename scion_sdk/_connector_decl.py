"""Connector declaration, content directories and resolution."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any

from scion_sdk.connector_hooks import (
    InlineTool,
    ReadinessProbe,
    Registration,
    Route,
    ToolRegistryEntry,
    content_subdir,
)
from scion_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    ConnectorIdentityError,
    connector_point,
    connector_version,
)


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
        extra_registrations: Callables run with a
            :class:`~scion_sdk.connector_hooks.RegistrationContext`
            after the tool surface registers, for registrations the SDK does
            not own.
        transports: Offered transports; defaults to every SDK transport.
        tool_prefix: Operation-tool name prefix; defaults to one derived from
            the fleet name.
        verbose_targets: Extra ``{client_cls, get_client, prefix?, manifest?,
            result_coercer?}`` operation-tool sources.
        verbose_register: Callable run last to register further tools.
        result_coercer: Coerces each operation result.
        action_dispatch: Keep action-routed tools whole instead of splitting.
        tool_registry: Explicit ``(tag, toggle_setting, registrar)`` entries,
            used instead of ``tools`` when a tag or toggle is not derived from
            the ``register_<tag>_tools`` name.
        action_tools: ``(tag, toggle_setting, registrar)`` entries whose
            action-routed tools are always served one typed tool per action.
        action_prefixes: Per-action tool prefix by routed tool name; the
            prefix defaults to the routed tool's name.
        inline_tools: Tool functions or fastmcp ``Tool`` values added with
            ``FastMCP.add_tool`` before the tool surface registers.
        routes: Extra HTTP routes added with ``FastMCP.custom_route``.
        readiness: An async backend probe served at ``/ready``; ``/health``
            stays liveness-only.
        content_root: Package-relative directory holding ``skills/``,
            ``prompts/``, ``ontology/`` and ``connectors/``; defaults to the
            package root.
    """

    instructions: str = ""
    api: type | None = None
    get_client: Callable[..., Any] | None = None
    tools: ModuleType | str | None = None
    extra_registrations: tuple[Registration, ...] = ()
    transports: Sequence[str] | None = None
    tool_prefix: str | None = None
    verbose_targets: tuple[dict[str, Any], ...] = ()
    verbose_register: Callable[[Any], None] | None = None
    result_coercer: Callable[[Any], Any] | None = None
    action_dispatch: bool = False
    tool_registry: tuple[ToolRegistryEntry, ...] = ()
    action_tools: tuple[ToolRegistryEntry, ...] = ()
    action_prefixes: Mapping[str, str] = field(default_factory=dict)
    inline_tools: tuple[InlineTool, ...] = ()
    routes: tuple[Route, ...] = ()
    readiness: ReadinessProbe | None = None
    content_root: str | None = None

    def __post_init__(self) -> None:
        if (self.api is None) != (self.get_client is None):
            raise ValueError("api and get_client are declared together or not at all")
        if self.tool_registry and self.tools is not None:
            raise ValueError("declare tools or tool_registry, not both")
        if self.action_prefixes and not self.action_tools:
            raise ValueError("action_prefixes name tools of action_tools")
        if self.content_root is not None:
            content_subdir(self.content_root)


@dataclass(frozen=True)
class ConnectorContentDirs:
    """Where a connector's content lives, by convention under its package.

    ``root`` is the package directory; ``content`` is the directory holding the
    content kinds (the package root unless ``content_root`` names another).
    """

    root: Path
    content: Path
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


def content_dirs(package: str, content_root: str | None = None) -> ConnectorContentDirs:
    """The content directories of ``package``, under ``content_root`` when given."""
    spec = importlib.util.find_spec(package.split(".", 1)[0])
    locations = list(spec.submodule_search_locations or []) if spec else []
    if not locations:
        raise ConnectorIdentityError(f"{package!r} is not an importable package")
    root = Path(locations[0])
    base = root if content_root is None else root / content_subdir(content_root)
    return ConnectorContentDirs(
        root=root,
        content=base,
        skills=base / "skills",
        prompts=base / "prompts",
        ontology=base / "ontology",
        connectors=base / "connectors",
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
                "scion_sdk.connector.Connector"
            )
        value = loaded
    return ResolvedConnector(
        name=point.name,
        package=point.package,
        distribution=point.distribution,
        version=connector_version(point.package),
        connector=value,
        dirs=content_dirs(point.package, value.content_root),
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
