"""Resource declarations must be validated at the actual pack boundary."""

from __future__ import annotations

import json

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.resource_descriptor import ResourceDeclarationError
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R074.5")
@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"ontology_class": "urn:test:Missing"}, "RESOURCE_UNMAPPED"),
        ({"access_kind": "invalid"}, "ACCESS_KIND_UNKNOWN"),
        ({"access_kind": "stream_topic"}, "ACCESS_KIND_UNKNOWN"),
        ({"pagination": "sync_token"}, "PAGINATION_UNDECLARED"),
        ({"pagination": None}, "PAGINATION_UNDECLARED"),
        ({"credential_ref": "test-secret"}, "SECRET_IN_CONTRACT"),
        ({"credential_ref": "env://SAFE_REFERENCE"}, None),
    ],
)
async def test_pack_refuses_invalid_served_resource_descriptors(override, reason):
    server = FastMCP("test-connector")
    descriptor = {
        "name": "items",
        "uri": "data://test-connector/items",
        "kind": "data",
        "origin": "declared",
        "mapping_status": "declared",
        "ontology_class": "urn:test:Item",
        "access_kind": "mcp_tool",
        "operation": "list_items",
        "key_field": "id",
        "pagination": "cursor",
        **override,
    }

    @server.resource("ontology://test/schema.ttl")
    def ontology() -> str:
        return "<urn:test:Item> a <http://www.w3.org/2002/07/owl#Class> ."

    @server.resource("connector://resources")
    def declaration() -> str:
        return json.dumps({"connector": "test-connector", "descriptors": [descriptor]})

    @server.resource("data://test-connector/items")
    def data() -> str:
        return json.dumps(descriptor)

    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        if reason is None:
            pack = await build_content_pack(
                session, connector="test-connector", kinds=(ResourceArtifactKind(),)
            )
            assert "connector://resources" in pack.resource_uris
        else:
            with pytest.raises(ResourceDeclarationError) as raised:
                await build_content_pack(
                    session, connector="test-connector", kinds=(ResourceArtifactKind(),)
                )
            assert raised.value.code == reason
            assert "test-secret" not in str(raised.value)
