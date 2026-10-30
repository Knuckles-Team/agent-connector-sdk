"""Native provider resources preserve authorized discovery and exact bytes."""

import asyncio
import json

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.transforms.search import RegexSearchTransform
from fastmcp.tools import Tool
from jsonschema import Draft202012Validator
from mcp.shared.exceptions import MCPError

from scion_sdk.mcp.schema_disclosure import (
    SchemaFragment,
    SchemaManifest,
    build_schema_disclosure,
    reconstruct_schema,
)
from scion_sdk.mcp.schema_disclosure_provider import (
    describe_schema_tools,
    register_schema_resources,
)


def provider(*, allowed=True):
    server = FastMCP("Public schema contract fixture")
    pattern = "[À-ž𐀀-𞤿]" * 6000
    inputs = {
        "type": "object",
        "properties": {"value": {"type": "string", "pattern": pattern}},
    }
    outputs = {"type": "object"}
    disclosure = build_schema_disclosure(
        (inputs, outputs),
        operation="readEntry",
        alias="operation_readEntry",
        source_sha256="b" * 64,
    )

    def read_entry(value=""):
        return {"value": value}

    tool = Tool.from_function(
        read_entry, name=disclosure.manifest.alias, auth=lambda ctx: allowed
    )
    tool = tool.model_copy(
        update={
            "parameters": inputs,
            "output_schema": outputs,
            "meta": {"openapi_schema": disclosure.manifest.model_dump()},
        }
    )
    server.add_tool(tool)
    search = RegexSearchTransform(
        max_results=1, search_result_serializer=describe_schema_tools
    )
    server.add_transform(search)
    register_schema_resources(server, search, {tool.name: disclosure})
    return server, disclosure


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R019")
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R045")
def test_native_search_manifest_fragments_and_json_schemas():
    server, disclosure = provider()

    async def run():
        async with Client(server) as client:
            navigation = await client.call_tool(
                "search_tools", {"pattern": "^operation_readEntry"}
            )
            rows = navigation.data
            if isinstance(rows, dict):
                rows = rows["result"]
            assert rows[0]["kind"] == "schema-navigation"
            selected = rows[0]["manifest"]
            assert len(json.dumps(rows).encode()) <= 32768
            received = await client.read_resource(selected["manifest_uri"])
            manifest = json.loads(received[0].text)
            assert manifest == selected == disclosure.manifest.model_dump()
            Draft202012Validator(SchemaManifest.model_json_schema()).validate(manifest)
            parts = []
            for index in range(manifest["fragment_count"]):
                uri = manifest["fragment_uri_template"].format(index=index)
                content = await client.read_resource(uri)
                value = json.loads(content[0].text)
                Draft202012Validator(SchemaFragment.model_json_schema()).validate(value)
                parts.append(value)
            rebuilt = reconstruct_schema(selected, parts)
            assert (
                rebuilt["inputSchema"]["properties"]["value"]["pattern"]
                == "[À-ž𐀀-𞤿]" * 6000
            )

    asyncio.run(run())


def test_auth_denial_also_denies_known_manifest_and_fragment_uris():
    server, disclosure = provider(allowed=False)

    async def run():
        async with Client(server) as client:
            for uri in (
                disclosure.manifest.manifest_uri,
                disclosure.manifest.fragment_uri_template.format(index=0),
            ):
                with pytest.raises(MCPError):
                    await client.read_resource(uri)

    asyncio.run(run())


@pytest.mark.parametrize("suffix", ["-1", "01", "true", "1000000"])
def test_native_fragment_index_refuses(suffix):
    server, disclosure = provider()

    async def run():
        async with Client(server) as client:
            with pytest.raises(MCPError):
                await client.read_resource(
                    disclosure.manifest.fragment_uri_template.format(index=suffix)
                )

    asyncio.run(run())


def test_stale_schema_uri_refuses():
    server, disclosure = provider()

    async def run():
        async with Client(server) as client:
            uri = disclosure.manifest.manifest_uri.replace(
                disclosure.manifest.schema_sha256, "0" * 64
            )
            with pytest.raises(MCPError):
                await client.read_resource(uri)

    asyncio.run(run())


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R019")
@pytest.mark.parametrize("field", ["parameters", "output_schema"])
def test_same_alias_schema_replacement_refuses_stale_metadata(field):
    server, disclosure = provider()

    async def run():
        async with Client(server) as client:
            original = await server.get_tool(disclosure.manifest.alias)
            changed = original.model_copy(update={field: {"type": "null"}})
            server.add_tool(changed)
            with pytest.raises(ToolError, match="schema identity differs"):
                await client.call_tool(
                    "search_tools", {"pattern": "^operation_readEntry"}
                )
            for uri in (
                disclosure.manifest.manifest_uri,
                disclosure.manifest.fragment_uri_template.format(index=0),
            ):
                with pytest.raises(MCPError):
                    await client.read_resource(uri)

    asyncio.run(run())
