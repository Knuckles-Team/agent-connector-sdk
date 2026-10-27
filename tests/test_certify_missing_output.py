"""Certification binds a missing output schema on the served MCP path."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.certify.certification import certify_connector
from agent_connector_sdk.certify.fingerprints import (
    output_schema_digest,
    tool_fingerprint,
)
from agent_connector_sdk.certify.verdicts import ToolStatus
from agent_connector_sdk.ingest.live_declaration import (
    register_live_declaration,
    source_meta,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R003")
async def test_served_certification_pins_missing_output_schema() -> None:
    server = FastMCP("demo-mcp")

    @server.tool(
        meta=source_meta(
            source_id="demo",
            record_type="Item",
            id_field="id",
            records_path="items",
            preset={
                "pagination": "cursor",
                "cursor_param": "cursor",
                "cursor_path": "cursor",
                "params_style": "args",
            },
        )
    )
    def read_items(cursor: str = ""):
        return {"items": [], "cursor": cursor}

    register_live_declaration(server, "demo-mcp")
    async with Client(server) as client:
        (tool,) = await client.list_tools()
        assert tool.output_schema is None
    endpoint = TransportEndpoint(in_process=server)
    report = await certify_connector(McpTransport(), endpoint, timeout_seconds=10)
    repeated = await certify_connector(McpTransport(), endpoint, timeout_seconds=10)

    assert report.passed and repeated.passed
    (verdict,) = report.verdicts
    assert verdict.status is ToolStatus.CERTIFIED
    assert verdict.live == tool_fingerprint(tool)
    assert verdict.output_schema_sha256 == output_schema_digest(tool)
    assert len(verdict.output_schema_sha256) == 64
    assert verdict.output_schema_sha256 == repeated.verdicts[0].output_schema_sha256
    assert verdict.output_schema_sha256 != output_schema_digest(
        SimpleNamespace(outputSchema={})
    )
    assert (
        report.document()["tools"][0]["output_schema_sha256"]
        == verdict.output_schema_sha256
    )
