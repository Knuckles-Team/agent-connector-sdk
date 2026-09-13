"""Derive verbose ``<tool>__<action>`` tools from condensed action-routed tools.

Extracted from ``agent_utilities.mcp.verbose_tools``. Each derived tool is
FastMCP's ``Tool.from_tool`` transformation of a condensed tool with ``action``
fixed and hidden, so it runs through the original handler (dependencies,
context and result coercion unchanged). Actions come from the tool's ``action``
enum, or from an action provider registered for a free-form ``action: str``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.tools import Tool
from fastmcp.tools.tool_transform import ArgTransform

from agent_connector_sdk.mcp.action_dispatch import DISCOVERY_ACTIONS, public_actions
from agent_connector_sdk.mcp.tool_mode import registered_tools

__all__ = ["autowire_verbose_from_condensed", "register_action_provider"]

_logger = logging.getLogger(__name__)

_ACTION_ARG = "action"
_PROVIDERS_ATTRIBUTE = "_verbose_action_providers"


def register_action_provider(mcp: Any, tool_name: str, actions: Any) -> None:
    """Record the runtime action set of a free-form condensed tool.

    ``actions`` is a list of names, a zero-argument callable returning one, or a
    client class whose public methods are the actions.
    """
    providers: dict[str, Any] = getattr(mcp, _PROVIDERS_ATTRIBUTE, {})
    providers[tool_name] = actions
    setattr(mcp, _PROVIDERS_ATTRIBUTE, providers)


def _provider_candidates(provider: Any) -> Any:
    if isinstance(provider, type):
        return public_actions(provider)
    return provider() if callable(provider) else provider


def _provider_actions(provider: Any) -> list[str]:
    try:
        candidates = _provider_candidates(provider)
    except Exception as exc:  # a broken provider skips only its own tool
        _logger.warning(
            "verbose autowire: action provider failed: %s",
            exc,
        )
        return []
    names = {item for item in candidates or [] if isinstance(item, str) and item}
    return sorted(names - set(DISCOVERY_ACTIONS))


def _action_enum(tool: Any) -> list[str]:
    schema = getattr(tool, "parameters", None)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    prop = properties.get(_ACTION_ARG) if isinstance(properties, dict) else None
    enum = prop.get("enum") if isinstance(prop, dict) else None
    if isinstance(enum, list) and all(isinstance(value, str) for value in enum):
        return [value for value in enum if value]
    return []


def _tool_actions(tool: Any, providers: dict[str, Any]) -> list[str]:
    enum = _action_enum(tool)
    provider = providers.get(getattr(tool, "name", None) or "")
    if enum or provider is None:
        return enum
    return _provider_actions(provider)


def _derive_for_tool(
    mcp: Any, tool_name: str, *, tool: Any, existing: set[str]
) -> list[str]:
    providers: dict[str, Any] = getattr(mcp, _PROVIDERS_ATTRIBUTE, {})
    tags = set(getattr(tool, "tags", None) or ())
    derived: list[str] = []
    for action in _tool_actions(tool, providers):
        verbose_name = f"{tool_name}__{action}"
        if verbose_name in existing:
            continue
        transform = {_ACTION_ARG: ArgTransform(default=action, hide=True)}
        mcp.add_tool(
            Tool.from_tool(
                tool,
                name=verbose_name,
                transform_args=transform,
                tags=tags | {"verbose"},
            )
        )
        derived.append(verbose_name)
    return derived


def autowire_verbose_from_condensed(mcp: Any) -> list[str]:
    """Derive the verbose surface of every condensed action-routed tool.

    Returns:
        The derived tool names.
    """
    source_tools = registered_tools(mcp)
    derived: list[str] = []
    for tool_name in sorted(source_tools):
        tool = source_tools[tool_name]
        if "__" in tool_name and "verbose" in (getattr(tool, "tags", None) or ()):
            continue
        derived.extend(
            _derive_for_tool(mcp, tool_name, tool=tool, existing=set(source_tools))
        )
    return derived
