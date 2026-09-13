"""``MCP_TOOL_MODE`` and the tags that describe a registered tool surface.

Extracted from ``agent_utilities.mcp.verbose_tools``. Modes: ``condensed``,
``verbose``, ``both`` and ``intent`` (default). ``intent`` registers condensed
tools and tags them :data:`GATED_TAG` so a fleet gateway can hold them back from
a default session view and reveal them on demand.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_connector_sdk.config import setting

__all__ = [
    "GATED_TAG",
    "GATED_TOOLS_ATTRIBUTE",
    "GRANULAR_TAG",
    "VALID_TOOL_MODES",
    "gated_tool_names",
    "registered_tools",
    "tool_mode",
]

_logger = logging.getLogger(__name__)

VALID_TOOL_MODES = ("condensed", "verbose", "both", "intent")
_DEFAULT_MODE = "intent"

#: Tag stamped on every condensed and verbose tool.
GRANULAR_TAG = "granular"
#: Tag stamped on condensed tools held back from a default session view.
GATED_TAG = "gated"
#: Server attribute recording the names tagged :data:`GATED_TAG`.
GATED_TOOLS_ATTRIBUTE = "_intent_gated_tools"


def tool_mode() -> str:
    """Return ``MCP_TOOL_MODE`` (``intent`` when unset or unrecognised)."""
    mode = str(setting("MCP_TOOL_MODE", _DEFAULT_MODE)).strip().lower()
    if mode in VALID_TOOL_MODES:
        return mode
    _logger.warning(
        "Unknown MCP_TOOL_MODE %r; expected one of %s. Falling back to %r.",
        mode,
        ", ".join(VALID_TOOL_MODES),
        _DEFAULT_MODE,
    )
    return _DEFAULT_MODE


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
    """Tool names tagged :data:`GATED_TAG` by ``intent`` mode."""
    return set(getattr(mcp, GATED_TOOLS_ATTRIBUTE, ()) or ())
