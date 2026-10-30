"""Scion SDK: the connector-facing SDK for the agent-packages fleet.

Public modules are imported by their own path (``scion_sdk.mcp.server``,
``scion_sdk.ports`` and so on). The package root exports the version
and, lazily, :class:`Connector` and :func:`run`, so importing it never pulls in
the MCP server stack.
"""

from __future__ import annotations

from typing import Any

from scion_sdk._version import __version__

__all__ = ["Connector", "__version__", "run"]


def __getattr__(name: str) -> Any:
    if name in ("Connector", "run"):
        from scion_sdk import connector

        return getattr(connector, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
