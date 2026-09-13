"""Register a connector's MCP tool surface according to ``MCP_TOOL_MODE``.

Extracted from ``agent_utilities.mcp.verbose_tools.register_tool_surface``, the
one entry point a connector's server module calls. It owns the mode selection,
so connectors need no branching. Two AU parameters are gone because no
connector used them: ``autowire_condensed`` (the auto-wire now always runs in
``verbose``/``both``) and ``force_condensed_registration`` (per-domain
``<TAG>TOOL`` toggles always apply).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.mcp.tool_mode import (
    GATED_TAG,
    GATED_TOOLS_ATTRIBUTE,
    GRANULAR_TAG,
    VALID_TOOL_MODES,
    registered_tools,
    tool_mode,
)
from agent_connector_sdk.mcp.verbose_autowire import (
    autowire_verbose_from_condensed,
    register_action_provider,
)
from agent_connector_sdk.mcp.verbose_tools import register_verbose_tools

__all__ = ["CondensedEntry", "register_tool_surface"]

#: ``(tag, toggle_setting, register_fn)`` for one condensed tool registrar.
CondensedEntry = tuple[str, str, Callable[[Any], Any]]

_TOGGLES_ATTRIBUTE = "_condensed_tool_toggles"
_SURFACE_HELPER_NAMES = frozenset({"register_verbose_tools", "register_tool_surface"})
_REGISTRAR_NAME = re.compile(r"register_(.+)_tools")


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
        and name not in _SURFACE_HELPER_NAMES
        and callable(getattr(tools_module, name))
    ]


def _register_condensed(
    mcp: Any, entries: list[CondensedEntry], *, gate: bool
) -> list[str]:
    toggles: dict[str, str] = getattr(mcp, _TOGGLES_ATTRIBUTE, {})
    gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
    extra_tags = {GRANULAR_TAG, GATED_TAG} if gate else {GRANULAR_TAG}
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
            tool.tags.update({tag, *extra_tags})
            toggles[name] = toggle
        gated.update(added if gate else ())
        registered_tags.append(tag)
    setattr(mcp, _TOGGLES_ATTRIBUTE, toggles)
    setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated)
    return registered_tags


def _verbose_targets(
    verbose_targets: list[dict[str, Any]] | None,
    client_cls: type | None,
    *,
    get_client: Any,
    extras: dict[str, Any],
) -> list[dict[str, Any]]:
    if verbose_targets is not None:
        return verbose_targets
    if client_cls is None or get_client is None:
        return []
    return [{"client_cls": client_cls, "get_client": get_client, **extras}]


def _register_verbose_surface(
    mcp: Any,
    targets: list[dict[str, Any]],
    *,
    service: str,
    verbose_register: Callable[[Any], None] | None,
    action_providers: dict[str, Any] | None,
) -> None:
    for target in targets:
        register_verbose_tools(
            mcp,
            target["client_cls"],
            target["get_client"],
            service=target.get("service", service),
            tool_prefix=target.get("tool_prefix"),
            manifest=target.get("manifest"),
        )
    if verbose_register is not None:
        verbose_register(mcp)
    for tool_name, actions in (action_providers or {}).items():
        register_action_provider(mcp, tool_name, actions)
    autowire_verbose_from_condensed(mcp)


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
    mode_override: str | None = None,
) -> list[str]:
    """Register a connector's tool surface for the configured ``MCP_TOOL_MODE``.

    Condensed registrars come from exactly one of ``tool_registry``
    (``[(tag, toggle_setting, fn)]``), ``tools_module`` (every
    ``register_<tag>_tools`` callable on it) or ``registrars``; each runs unless
    its ``<TAG>TOOL`` setting is false. Condensed tools register in every mode
    because the verbose aliases route through them; they are gated in
    ``intent`` mode, and in ``verbose`` mode when a verbose surface exists.

    In ``verbose``/``both`` the verbose surface comes from ``client_cls`` with
    ``get_client`` (or ``verbose_targets`` for multi-client connectors),
    ``verbose_register``, and the condensed auto-wire.

    Returns:
        The condensed tags that registered.

    Raises:
        ValueError: ``mode_override`` is not a valid mode, or a registrar entry
            is malformed.
    """
    if mode_override is not None and mode_override not in VALID_TOOL_MODES:
        raise ValueError(f"mode_override must be one of {VALID_TOOL_MODES}")
    mode = mode_override or tool_mode()
    targets = _verbose_targets(
        verbose_targets,
        client_cls,
        get_client=get_client,
        extras={"tool_prefix": tool_prefix, "manifest": manifest},
    )
    has_verbose = bool(targets) or verbose_register is not None
    registered_tags = _register_condensed(
        mcp,
        _condensed_entries(tool_registry, tools_module, registrars),
        gate=mode == "intent" or (mode == "verbose" and has_verbose),
    )
    if mode in ("verbose", "both"):
        _register_verbose_surface(
            mcp,
            targets,
            service=service,
            verbose_register=verbose_register,
            action_providers=action_providers,
        )
    return registered_tags
