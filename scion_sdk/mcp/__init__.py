"""MCP server scaffolding for connectors: server factory, auth, tool surface.

Submodules are imported by path (``scion_sdk.mcp.server`` and so on).
This package needs the ``mcp`` extra: ``pip install "scion-sdk[mcp]"``.
"""

from scion_sdk._extras import require_mcp_extra

require_mcp_extra("scion_sdk.mcp")
