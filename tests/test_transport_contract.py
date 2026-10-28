"""Typed transport declarations and the live access-contract parser."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import cast

import pytest

from agent_connector_sdk._contract_fields import AUTH_MODELS, STREAM_MODES
from agent_connector_sdk.access_contract import (
    AccessContractError,
    TransportContract,
    parse_access_contracts,
)


def _contract(kind: str, pushdown: str = '"time_range"') -> str:
    return f'''@prefix ac: <https://knuckles-team.github.io/agent-connector-sdk/access#> .
@prefix ex: <https://example.invalid/> .
ex:feed a ac:AccessContract ; ac:classIri ex:Event ; ac:sourceId "source" ;
 ac:entity "event" ; ac:keyField "id" ; ac:accessKind "{kind}" ;
 ac:operation "read" ; ac:authModel "sasl" ; ac:streaming "offset" ;
 ac:pushdown {pushdown} .'''


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R069.1")
def test_transport_contract_round_trips() -> None:
    assert "sasl" in AUTH_MODELS
    assert "offset" in STREAM_MODES
    mutable = {"time_range"}
    value = TransportContract(
        "stream_topic",
        "sasl",
        streaming="offset",
        pushdown=cast(frozenset[str], mutable),
    )
    mutable.add("filter")
    assert value.pushdown == frozenset({"time_range"})
    assert TransportContract(**asdict(value)) == value
    assert TransportContract.from_json(json.loads(json.dumps(value.to_json()))) == value
    with pytest.raises(ValueError, match="duplicate"):
        TransportContract.from_json(
            value.to_json() | {"pushdown": ["time_range", "time_range"]}
        )
    with pytest.raises(ValueError, match="protocol"):
        TransportContract("unknown", "none")
    with pytest.raises(ValueError, match="pushdown"):
        TransportContract("http_endpoint", "none", pushdown=frozenset({"unknown"}))


def test_turtle_reads_stream_contract_and_refuses_unsupported_pushdown() -> None:
    (value,) = parse_access_contracts(_contract("stream_topic"))
    assert value.transport == TransportContract(
        "stream_topic", "sasl", streaming="offset", pushdown=frozenset({"time_range"})
    )
    with pytest.raises(AccessContractError, match="invalid transport declaration"):
        parse_access_contracts(_contract("stream_topic", '"filter"'))


def test_stream_transport_requires_auth_model() -> None:
    with pytest.raises(AccessContractError, match="missing ac:authModel"):
        parse_access_contracts(
            _contract("stream_topic").replace(' ac:authModel "sasl" ;', "")
        )


@pytest.mark.parametrize(
    "protocol",
    [
        "http_endpoint",
        "graphql_query",
        "grpc_method",
        "odata_entity_set",
        "soap_operation",
        "jsonrpc_method",
        "mcp_tool",
        "a2a_skill",
        "sparql_endpoint",
        "graph_endpoint",
        "virtual_graph",
        "stream_topic",
        "change_feed",
        "webhook_event",
        "event_stream",
        "file_store",
        "directory",
        "mailbox",
        "calendar_collection",
    ],
)
def test_declared_protocols_round_trip(protocol: str) -> None:
    contract = TransportContract(protocol, "none")
    assert TransportContract(**asdict(contract)) == contract
