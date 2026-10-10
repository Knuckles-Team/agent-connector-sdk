"""Native prompt/resource/resource-template registration on the connector server."""

from __future__ import annotations

import pytest
from fastmcp import Client

from agent_connector_sdk.mcp.server import create_mcp_server


# spec: GRAPHOS-FLEET-R007.1
@pytest.mark.spec("GRAPHOS-FLEET-R007.1")
async def test_create_mcp_server_serves_native_prompts_resources_and_templates() -> (
    None
):
    _, mcp, _ = create_mcp_server("native-mcp", version="1.0.0", command_args=[])
    async with Client(mcp) as client:
        prompts = await client.list_prompts()
        assert any(prompt.name == "connector-status" for prompt in prompts)

        resources = await client.list_resources()
        assert any(str(resource.uri) == "connector://status" for resource in resources)

        templates = await client.list_resource_templates()
        assert any(
            template.uriTemplate == "connector://capability/{capability}"
            for template in templates
        )

        read = await client.read_resource("connector://status")
        assert read[0].text and "native-mcp" in read[0].text

        read_template = await client.read_resource("connector://capability/search")
        assert read_template[0].text and "search" in read_template[0].text
