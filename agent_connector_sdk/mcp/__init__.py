"""MCP server scaffolding for connectors: server factory, auth, tool surface.

Submodules are imported by path (``agent_connector_sdk.mcp.server`` and so on).
This package needs the ``mcp`` extra: ``pip install "agent-connector-sdk[mcp]"``.
"""

from agent_connector_sdk._extras import require_mcp_extra

require_mcp_extra("agent_connector_sdk.mcp")
