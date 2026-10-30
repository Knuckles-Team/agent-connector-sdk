"""Native prompt/resource/resource-template registration on the connector server."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastmcp import Client

from scion_sdk.artifacts.pack import build_content_pack
from scion_sdk.artifacts.resources import ResourceArtifactKind
from scion_sdk.artifacts.skills import SkillArtifactKind
from scion_sdk.mcp.content import ConnectorContent
from scion_sdk.mcp.server import create_mcp_server
from scion_sdk.ports.errors import MalformedArtifactError
from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.transports.mcp import McpTransport


# spec: ARBORA-FLEET-R007.1
@pytest.mark.spec("ARBORA-FLEET-R007.1")
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


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R005")
async def test_native_status_does_not_block_packaged_content_capture(
    package_root: Path,
) -> None:
    _, mcp, _ = create_mcp_server(
        "native-mcp",
        version="1.0.0",
        command_args=[],
        content=ConnectorContent(
            connector="demo-agent",
            package_root=package_root,
            package_version="1.0.0",
        ),
    )
    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        pack = await build_content_pack(
            session,
            connector="demo-agent",
            kinds=(SkillArtifactKind(), ResourceArtifactKind()),
        )
        assert "native-mcp" in await session.read_resource("connector://status")
        assert "search" in await session.read_resource("connector://capability/search")
    assert pack.resource_uris == {
        "connector://resources",
        "ontology://demo-agent/demo.ttl",
        "shapes://demo-agent/demo.shapes.ttl",
        "skill://demo-reader/SKILL.md",
    }
    assert {entry.uri for entry in pack.archive.entries} == pack.resource_uris


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R005")
@pytest.mark.parametrize(
    "uri",
    [
        "mystery://content",
        "connector://unexpected",
        "connector://status/extra",
        "connector://status?variant=1",
    ],
)
async def test_native_status_exclusion_keeps_unknown_resources_rejected(
    uri: str,
) -> None:
    _, mcp, _ = create_mcp_server("native-mcp", version="1.0.0", command_args=[])

    @mcp.resource(uri)
    def unknown_resource() -> str:
        return "unrecognized content"

    async with McpTransport().session(TransportEndpoint(in_process=mcp)) as session:
        with pytest.raises(
            MalformedArtifactError, match=re.escape(uri) + ".*unknown scheme"
        ):
            await build_content_pack(
                session, connector="demo-agent", kinds=(ResourceArtifactKind(),)
            )
