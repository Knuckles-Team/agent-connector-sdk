"""Typed mappings must not be accepted without engine capability evidence."""

import asyncio
import json

import pytest
from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackEntryContent,
)
from epistemic_graph.generated.connector_pack import PackEntryKind
from live_engine import live_ingest, scoped_client  # noqa: F401

from agent_connector_sdk.artifacts.pack import CapturedConnectorPack
from agent_connector_sdk.sinks.epistemic_graph import (
    EpistemicGraphSink,
    _require_supported_mapping_contract,
)


def _pack(datatypes, *, declaration=None):
    server = ConnectorPackEntryContent(
        kind=PackEntryKind.MCP_SERVER,
        uri="mcp-server://typed-test",
        name="typed-test",
        media_type="application/json",
        body=b'{"name":"typed-test"}',
    )
    mapping = {"record_type": "Observation", "fields": {"time": "observationTime"}}
    if datatypes is not None:
        mapping["datatypes"] = datatypes
    resource = ConnectorPackEntryContent(
        kind=PackEntryKind.RESOURCE,
        uri="connector://resources",
        name="resources",
        media_type="application/json",
        body=declaration
        if declaration is not None
        else json.dumps(
            {"connector": "typed-test", "schema_mappings": {"Observation": mapping}}
        ).encode(),
    )
    return CapturedConnectorPack(
        connector="typed-test",
        server_package_version="1",
        archive=ConnectorPackArchiveBuilder.build(server, (resource,)),
        resource_uris=frozenset({resource.uri}),
    )


async def _unexpected_authority(connector):
    raise AssertionError(f"authority requested for refused pack {connector}")


@pytest.mark.parametrize("datatypes", [{"time": "xsd:dateTime"}, []])
async def test_typed_or_malformed_mapping_refused_before_pack_authority(datatypes):
    pack = _pack(datatypes)
    sink = EpistemicGraphSink(object(), _unexpected_authority)
    with pytest.raises(ValueError, match="engine capability negotiation"):
        await sink.import_pack(pack)


@pytest.mark.parametrize("datatypes", [None, {}])
def test_untyped_mapping_remains_admissible(datatypes):
    _require_supported_mapping_contract(_pack(datatypes))


async def test_duplicate_nested_datatypes_refused_before_pack_authority():
    declaration = (
        b'{"connector":"typed-test","schema_mappings":{"Observation":'
        b'{"datatypes":{"time":"xsd:dateTime"},"datatypes":{}}}}'
    )
    sink = EpistemicGraphSink(object(), _unexpected_authority)
    with pytest.raises(ValueError, match="connector resource declaration is invalid"):
        await sink.import_pack(_pack(None, declaration=declaration))


def test_real_engine_refuses_typed_pack_before_authority(live_ingest):  # noqa: F811
    async def exercise():
        client = await scoped_client(["*"])
        try:
            await client.query.cypher_read("MATCH (n) RETURN n LIMIT 1")
            sink = EpistemicGraphSink(client, _unexpected_authority)
            with pytest.raises(ValueError, match="engine capability negotiation"):
                await sink.import_pack(_pack({"time": "xsd:dateTime"}))
        finally:
            await client.close()

    asyncio.run_coroutine_threadsafe(exercise(), live_ingest._loop).result(30)
