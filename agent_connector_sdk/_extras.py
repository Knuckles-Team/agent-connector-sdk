"""Clear errors for features that need an optional extra of the base install."""

from __future__ import annotations

import importlib

__all__ = ["require_mcp_extra"]


def require_mcp_extra(feature: str) -> None:
    """Raise ``ImportError`` naming the ``mcp`` extra when fastmcp or mcp is absent."""
    missing = []
    for name in ("fastmcp", "mcp"):
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise ImportError(
            f"{feature} needs {' and '.join(missing)}, which the base install of "
            'agent-connector-sdk leaves out; install "agent-connector-sdk[mcp]"'
        )
