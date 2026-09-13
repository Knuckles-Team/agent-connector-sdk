"""agent-connector-sdk: the connector-facing SDK for the agent-packages fleet.

Public modules are imported by their own path (``agent_connector_sdk.mcp.server``,
``agent_connector_sdk.ports`` and so on); this package root deliberately exports
only the version so that importing it never pulls in the MCP server stack.
"""

from agent_connector_sdk._version import __version__

__all__ = ["__version__"]
