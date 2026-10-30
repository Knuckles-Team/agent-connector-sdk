"""Read-only hints require host-supplied observations for the exact tool."""

import pytest
from fastmcp import FastMCP
from mcp_types import ToolAnnotations

from agent_connector_sdk.artifacts.tool_facts import SideEffect, facts_from_declaration
from agent_connector_sdk.certify.certification import certify_connector
from agent_connector_sdk.certify.read_only_check import (
    ReadOnlyOutcome,
    ToolFixture,
    check_read_only,
)
from agent_connector_sdk.certify.verdicts import ToolStatus
from agent_connector_sdk.ingest.live_declaration import (
    register_live_declaration,
    source_meta,
)
from agent_connector_sdk.manifest.live_contract import validate_live_tool_contract
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R045.9")
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R045.10")
async def test_mcp_hint_requires_matching_write_free_fixture() -> None:
    server = FastMCP("demo")

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=True),
        meta=source_meta(
            source_id="items",
            record_type="Item",
            id_field="id",
            preset={"params_style": "args"},
        ),
    )
    def read_items() -> dict:
        return {"items": []}

    register_live_declaration(server, "demo")
    transport = McpTransport()
    endpoint = TransportEndpoint(in_process=server)
    unproven = await certify_connector(transport, endpoint, timeout_seconds=10)
    assert not unproven.passed
    assert unproven.verdicts[0].status is ToolStatus.UNPROVEN
    assert not unproven.verdicts[0].live
    async with transport.session(endpoint) as session:
        pin = validate_live_tool_contract(
            await session.list_tools(), tool_name="read_items"
        ).compatibility_sha256
    fixture = ToolFixture(
        tool="read_items", fingerprint=pin, arguments={}, observed_effects=frozenset()
    )
    passed = await certify_connector(
        transport, endpoint, timeout_seconds=10, fixtures={"read_items": fixture}
    )
    assert passed.passed
    written = fixture.model_copy(
        update={"observed_effects": frozenset({SideEffect.EXTERNAL_WRITE})}
    )
    violated = await certify_connector(
        transport, endpoint, timeout_seconds=10, fixtures={"read_items": written}
    )
    assert violated.verdicts[0].status is ToolStatus.READ_ONLY_VIOLATION
    assert not violated.verdicts[0].live
    stale = fixture.model_copy(update={"fingerprint": "0" * 64})
    rejected = await certify_connector(
        transport, endpoint, timeout_seconds=10, fixtures={"read_items": stale}
    )
    assert rejected.verdicts[0].status is ToolStatus.UNPROVEN


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R045.10")
async def test_non_preset_read_only_hint_is_not_silently_certified() -> None:
    server = FastMCP("demo")

    @server.tool(
        meta=source_meta(
            source_id="items",
            record_type="Item",
            id_field="id",
            preset={"params_style": "args"},
        )
    )
    def read_items() -> dict:
        return {"items": []}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def auxiliary() -> dict:
        return {"items": []}

    register_live_declaration(server, "demo")
    report = await certify_connector(
        McpTransport(), TransportEndpoint(in_process=server), timeout_seconds=10
    )
    assert not report.passed
    assert (
        next(v for v in report.verdicts if v.tool == "auxiliary").status
        is ToolStatus.UNPROVEN
    )


def test_read_only_check_rejects_fixture_for_another_tool() -> None:
    facts = facts_from_declaration(
        {
            "name": "query",
            "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True},
        }
    )
    fixture = ToolFixture(
        tool="other", fingerprint="a" * 64, arguments={}, observed_effects=frozenset()
    )
    assert (
        check_read_only(facts, fixture, tool="query", fingerprint="a" * 64)
        is ReadOnlyOutcome.UNPROVEN
    )
