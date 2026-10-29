"""Certification refuses unscored readable-form declarations on live tools."""

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.certify.certification import certify_connector
from agent_connector_sdk.certify.verdicts import ToolStatus
from agent_connector_sdk.ingest.live_declaration import (
    register_live_declaration,
    source_meta,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R048.4")
@pytest.mark.parametrize("declared_on_preset", [True, False])
@pytest.mark.parametrize("question_set_ref", [None, "questions.json"])
async def test_unscored_form_is_refused(
    declared_on_preset: bool, question_set_ref: str | None
) -> None:
    server = FastMCP("demo-mcp")
    form = {"template_id": "default", "question_set_ref": question_set_ref}
    preset_meta = source_meta(
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
    if declared_on_preset:
        preset_meta["eg.annotations"] = {"readable_form": form}

    @server.tool(meta=preset_meta)
    def read_items(cursor: str = ""):
        return {"items": [], "cursor": cursor}

    if not declared_on_preset:

        @server.tool(meta={"eg.annotations": {"readable_form": form}})
        def analysis():
            return {"terms": []}

    register_live_declaration(server, "demo-mcp")
    report = await certify_connector(
        McpTransport(), TransportEndpoint(in_process=server), timeout_seconds=10
    )
    assert not report.passed
    rejected = [
        verdict
        for verdict in report.verdicts
        if verdict.status is ToolStatus.UNSCORED_READABLE_FORM
    ]
    assert len(rejected) == 1
    assert rejected[0].tool == ("read_items" if declared_on_preset else "analysis")
    assert any(
        tool["status"] == "unscored_readable_form"
        for tool in report.document()["tools"]
    )
