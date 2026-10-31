"""Registered-tool lookup and action-split helpers shared by the tool surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scion_sdk.mcp.action_split import split_action_tool

#: Tag stamped on a registrar tool kept as an opt-in action-dispatch tool.
ACTION_DISPATCH_TAG = "action-dispatch"
#: Server attribute recording the names tagged ``GATED_TAG``.
GATED_TOOLS_ATTRIBUTE = "_intent_gated_tools"


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


def _is_action_dispatch(tool: Any) -> bool:
    """Whether a registered tool routes an ``action`` string to client methods."""
    schema = getattr(tool, "parameters", None) or {}
    return "action" in (schema.get("properties") or {})


def _flat_operations(clients: dict[Any, dict[str, str]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for operations in clients.values():
        for method, tool in operations.items():
            names.setdefault(method, tool)
    return names


def _split_registered(mcp: Any, name: str, tool: Any, **kwargs: Any) -> None:
    """Split one action tool and record the resulting names as gated."""
    gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
    added = split_action_tool(
        mcp,
        name,
        tool,
        taken=set(registered_tools(mcp)) - {name},
        **kwargs,
    )
    if name not in added:
        gated.discard(name)
    gated.update(added)
    setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated)


def _gate_operations(mcp: Any, operations: list[str]) -> None:
    if operations:
        gated: set[str] = getattr(mcp, GATED_TOOLS_ATTRIBUTE, set())
        setattr(mcp, GATED_TOOLS_ATTRIBUTE, gated | set(operations))


def _run_verbose_register(mcp: Any, verbose_register: Callable[[Any], None]) -> None:
    before = registered_tools(mcp)
    verbose_register(mcp)
    after = registered_tools(mcp)
    collisions = {
        name for name in before if name in after and after[name] is not before[name]
    }
    if collisions:
        raise ValueError(
            f"verbose tool name collides with a registered tool: {sorted(collisions)}"
        )
