"""Serve one host-authorized enterprise dispatcher through MCP."""

from typing import Any

from fastmcp import FastMCP

from scion_sdk.identity import current_actor
from scion_sdk.mcp.action_dispatch import dispatch_async
from scion_sdk.mcp.tool_surface import registered_tools
from scion_sdk.vendor_extractors.enterprise_contract import (
    EnterpriseOperation,
)
from scion_sdk.vendor_extractors.enterprise_dispatch import (
    EnterpriseDispatcher,
)


class _EnterpriseClient:
    def __init__(self, dispatcher: EnterpriseDispatcher) -> None:
        self._dispatcher = dispatcher

    async def execute(self, request: EnterpriseOperation) -> dict[str, Any]:
        actor = current_actor()
        return (await self._dispatcher.execute(actor, request)).model_dump(mode="json")


def register_enterprise_tools(
    server: FastMCP, dispatcher: EnterpriseDispatcher
) -> None:
    """Register a single operation without choosing a provider or granting authority."""
    if "enterprise_operation" in registered_tools(server):
        raise ValueError("enterprise_operation is already registered")
    client = _EnterpriseClient(dispatcher)

    @server.tool(name="enterprise_operation")
    async def enterprise_operation(request: EnterpriseOperation) -> Any:
        return await dispatch_async(client, "execute", {"request": request})
