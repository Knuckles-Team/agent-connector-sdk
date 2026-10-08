"""Register a connector's condensed, intent-gated MCP tool surface.

Extracted from ``agent_utilities.mcp.verbose_tools.register_tool_surface``, the
one entry point a connector's server module calls. ``MCP_TOOL_MODE`` and its
``condensed``/``verbose``/``both``/``intent`` branches are gone: one condensed
intent contract (agent-utilities#54) replaces them. Every connector now
registers exactly the condensed action-routed tools, each tagged
:data:`GATED_TAG` so a fleet gateway holds it back from a default session view
and reveals it on demand.

``client_cls``, ``get_client``, ``verbose_targets``, ``verbose_register`` and
``action_providers`` remain accepted parameters, ignored: they built the
retired verbose 1:1 tool surface (one named tool per API-client method). They
stay so the fleet's existing call sites need no edit.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from agent_connector_sdk.config import setting

__all__ = [
    "GATED_TAG",
    "GATED_TOOLS_ATTRIBUTE",
    "GRANULAR_TAG",
    "CondensedEntry",
    "gated_tool_names",
    "register_tool_surface",
    "registered_tools",
]

#: ``(tag, toggle_setting, register_fn)`` for one condensed tool registrar.
CondensedEntry = tuple[str, str, Callable[[Any], Any]]

#: Tag stamped on every condensed tool.
GRANULAR_TAG = "granular"
#: Tag stamped on every condensed tool, held back from a default session view.
GATED_TAG = "gated"
#: Server attribute recording the names tagged :data:`GATED_TAG`.
GATED_TOOLS_ATTRIBUTE = "_intent_gated_tools"

_TOGGLES_ATTRIBUTE = "_condensed_tool_toggles"
_REGISTRAR_NAME = re.compile(r"register_(.+)_tools")


def registered_tools(mcp: Any) -> dict[str, Any]:
    """``{tool_name: tool}`` currently registered on the server's local provider."""
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        return {}
    return {
        value.name: value
        for key, value in components.items()
        if str(key).startswith("tool:") and getattr(value, "name", None)
    }


def gated_tool_names(mcp: Any) -> set[str]:
    """Tool names tagged :data:`GATED_TAG`."""
    return set(getattr(mcp, GATED_TOOLS_ATTRIBUTE, ()) or ())


def _entry(item: Any) -> CondensedEntry:
    if isinstance(item, tuple | list):
        if len(item) != 3 or not callable(item[2]):
            raise ValueError(
                "a registrar entry must be (tag, toggle_setting, register_fn)"
            )
        return str(item[0]), str(item[1]), item[2]
    if not callable(item):
        raise ValueError("a registrar must be callable or a (tag, setting, fn) entry")
    match = _REGISTRAR_NAME.fullmatch(getattr(item, "__name__", ""))
    tag = match.group(1) if match else str(getattr(item, "__name__", "tools"))
    return tag, f"{tag.upper()}TOOL", item


def _condensed_entries(
    tool_registry: list[Any] | None, tools_module: Any, registrars: list[Any] | None
) -> list[CondensedEntry]:
    if tool_registry:
        return [_entry(item) for item in tool_registry]
    if tools_module is None:
        return [_entry(item) for item in registrars or []]
    return [
        _entry(getattr(tools_module, name))
        for name in sorted(vars(tools_module))
        if _REGISTRAR_NAME.fullmatch(name)
        and name != "register_tool_surface"
        and callable(getattr(tools_module, name))
    ]


def _register_condensed(mcp: Any, entries: list[CondensedEntry]) -> list[str]:
    toggles: dict[str, str] = getattr(mcp, _TOGGLES_ATTRIBUTE, {})
    gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
    registered_tags: list[str] = []
    for tag, toggle, register_fn in entries:
        if not setting(toggle, True):
            continue
        before = set(registered_tools(mcp))
        register_fn(mcp)
        added = {
            name: tool
            for name, tool in registered_tools(mcp).items()
            if name not in before
        }
        for name, tool in added.items():
            tool.tags.update({tag, GRANULAR_TAG, GATED_TAG})
            toggles[name] = toggle
        gated.update(added)
        registered_tags.append(tag)
    setattr(mcp, _TOGGLES_ATTRIBUTE, toggles)
    setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated)
    return registered_tags


def register_tool_surface(
    mcp: Any,
    *,
    service: str,
    client_cls: type | None = None,
    get_client: Any = None,
    tool_registry: list[Any] | None = None,
    tools_module: Any = None,
    registrars: list[Any] | None = None,
    manifest: list[dict[str, Any]] | None = None,
    tool_prefix: str | None = None,
    verbose_targets: list[dict[str, Any]] | None = None,
    verbose_register: Callable[[Any], None] | None = None,
    action_providers: dict[str, Any] | None = None,
) -> list[str]:
    """Register a connector's condensed, intent-gated MCP tool surface.

    Condensed registrars come from exactly one of ``tool_registry``
    (``[(tag, toggle_setting, fn)]``), ``tools_module`` (every
    ``register_<tag>_tools`` callable on it) or ``registrars``; each runs
    unless its ``<TAG>TOOL`` setting is false. Every registered tool is tagged
    :data:`GRANULAR_TAG` and :data:`GATED_TAG` — the one condensed intent
    contract: a fleet gateway reveals it on demand.

    ``service``, ``client_cls``, ``get_client``, ``manifest``, ``tool_prefix``,
    ``verbose_targets``, ``verbose_register`` and ``action_providers`` are
    accepted and ignored. They built the retired verbose 1:1 tool surface;
    they stay so existing call sites across the fleet need no edit.

    Returns:
        The condensed tags that registered.

    Raises:
        ValueError: a registrar entry is malformed.
    """
    del (
        service,
        client_cls,
        get_client,
        manifest,
        tool_prefix,
        verbose_targets,
        verbose_register,
        action_providers,
    )
    return _register_condensed(
        mcp, _condensed_entries(tool_registry, tools_module, registrars)
    )
