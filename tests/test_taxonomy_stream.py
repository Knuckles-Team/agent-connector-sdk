"""Taxonomy sources authorize callers and expose resumable certified pages."""

import json
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from scion_sdk.http.options import HttpClientOptions
from scion_sdk.http.retry import RetryPolicy
from scion_sdk.taxonomy.provider import TaxonomyProvider
from scion_sdk.taxonomy.stream import register_taxonomy_stream
from scion_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.spec("SCION-SOURCE-INGEST-R009")
@pytest.mark.asyncio
async def test_served_pages_preserve_state_on_refusal():
    @asynccontextmanager
    async def quota(name):
        yield

    allowed = False

    async def authorize(tenant, ctx):
        return allowed and tenant == "tenant-a"

    def body(identifier):
        return json.dumps(
            {
                "key": identifier,
                "nubKey": identifier,
                "scientificName": f"Taxon {identifier}",
            }
        ).encode()

    with ScriptedHttpServer(
        ScriptedResponse(body=body(1)),
        ScriptedResponse(status=503),
        ScriptedResponse(body=body(2)),
    ) as server:
        provider = TaxonomyProvider(
            provider="gbif",
            http=HttpClientOptions(
                base_url=server.base_url,
                pin_egress=True,
                allow_loopback=True,
                retry=RetryPolicy(max_attempts=1),
            ),
            quota=quota,
            max_bytes=1024,
        )
        mcp = FastMCP("taxonomy")
        register_taxonomy_stream(
            mcp,
            provider,
            ["1", "2"],
            tenant="tenant-a",
            batch_size=1,
            authorize=authorize,
            name="taxa",
            connector="taxonomy",
        )
        register_taxonomy_stream(
            mcp,
            provider,
            ["1", "2"],
            tenant="tenant-a",
            batch_size=2,
            authorize=authorize,
            name="taxa_changed_policy",
            connector="taxonomy",
        )
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("taxa", {})
            assert not server.requests
            allowed = True
            first = (await client.call_tool("taxa", {})).structured_content
            assert first["records"][0]["id"] == "GBIF:1"
            checkpoint = first["checkpoint"]
            with pytest.raises(ToolError):
                await client.call_tool("taxa_changed_policy", {"state": checkpoint})
            assert len(server.requests) == 1
            with pytest.raises(ToolError):
                await client.call_tool("taxa", {"state": checkpoint})
            second = (
                await client.call_tool("taxa", {"state": checkpoint})
            ).structured_content
            assert second["records"][0]["id"] == "GBIF:2"
            assert second["next"] is None
            assert [request.path for request in server.requests] == [
                "/species/1",
                "/species/2",
                "/species/2",
            ]
