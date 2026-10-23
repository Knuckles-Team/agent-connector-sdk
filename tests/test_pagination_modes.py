"""Page and offset pagination: preset validation, paging and the conformance kit."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from fleet_declarations import DECLARATIONS
from fleet_fixtures import (
    FakeArchiveBox,
    archivebox_snapshots,
    build_enumerated_archivebox_server,
    build_table_server,
)
from pydantic import ValidationError

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.adapters.mcp_tool_paging import next_position, page_params
from agent_connector_sdk.manifest.model import SchemaMapping, SyncSpec
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.testing.results import SessionFactory, assert_conformant
from agent_connector_sdk.testing.source_adapters import run_source_adapter_suite
from agent_connector_sdk.transports.mcp import McpTransport

TABLE_WIRE_SHA256 = "55996ec96eb3987015ce7d6ec11cb177141c802577ed087d0c07f70a36d37b16"
SERVICENOW_STYLE: dict[str, Any] = {
    "server": "table-mcp",
    "tool": "table_records",
    "action": "list",
    "records_path": "result",
    "id_field": "sys_id",
    "updated_field": "sys_updated_on",
    "pagination": "offset",
    "page_kind": "offset",
    "page_param": "sysparm_offset",
    "page_size_param": "sysparm_limit",
    "page_size": 2,
}


def _sessions(build: Callable[[], object]) -> SessionFactory:
    def open_session() -> AbstractAsyncContextManager[McpSession]:
        return McpTransport().session(TransportEndpoint(in_process=build()))

    return open_session


def test_fleet_page_and_offset_vocabulary_validates() -> None:
    for name, raw in (
        (
            "archivebox",
            {"page_kind": "number", "page_param": "page", "page_size_param": "limit"},
        ),
        (
            "github",
            {
                "page_kind": "number",
                "page_param": "page",
                "page_size_param": "per_page",
            },
        ),
        ("numbered", {"page_kind": "number", "page_param": "page", "start_page": 1}),
    ):
        preset = ToolPreset.from_mapping(
            name, {"server": "s", "tool": "t", "pagination": "page", **raw}
        )
        assert preset.pagination == "page"
    erpnext = {
        "pagination": "offset",
        "page_param": "limit_start",
        "page_size_param": "limit_page_length",
    }
    assert (
        ToolPreset.from_mapping(
            "erpnext", {"server": "s", "tool": "t", **erpnext}
        ).page_kind
        is None
    )
    assert ToolPreset.from_mapping("servicenow", SERVICENOW_STYLE).page_kind == "offset"


def test_pagination_modes_reject_what_does_not_apply() -> None:
    base = {"name": "p", "server": "s", "tool": "t"}
    for extra, message in (
        (
            {"pagination": "page", "page_param": "offset", "page_kind": "offset"},
            "does not apply",
        ),
        (
            {"pagination": "page", "page_param": "page", "page_kind": "page"},
            "Input should be 'number' or 'offset'",
        ),
        (
            {
                "pagination": "cursor",
                "cursor_param": "c",
                "cursor_path": "c",
                "page_kind": "number",
            },
            "does not apply",
        ),
        ({"pagination": "offset"}, "needs page_param"),
        (
            {"pagination": "offset", "page_param": "offset", "start_page": 1},
            "start_page",
        ),
    ):
        with pytest.raises(ValidationError, match=message):
            ToolPreset.model_validate({**base, **extra})


def test_page_and_offset_positions() -> None:
    page = ToolPreset(
        name="p",
        server="s",
        tool="t",
        pagination="page",
        page_kind="number",
        page_param="page",
        page_size_param="limit",
        page_size=2,
        params_style="args",
    )
    assert page_params(page, {}, None) == {"page": 0, "limit": 2}
    assert next_position(page, {"page": 4}, result={}, raw=[{}, {}]) == {"page": 5}
    offset = ToolPreset.from_mapping(
        "servicenow", {**SERVICENOW_STYLE, "params_style": "args"}
    )
    assert page_params(offset, {"offset": 4}, None) == {
        "sysparm_offset": 4,
        "sysparm_limit": 2,
    }
    assert next_position(offset, {"offset": 4}, result={}, raw=[{}, {}]) == {
        "offset": 6
    }
    assert next_position(offset, {"offset": 6}, result={}, raw=[{}]) is None


async def test_page_mode_adapter_passes_the_conformance_kit() -> None:
    declared = DECLARATIONS["archivebox-api"]
    source = declared["sources"][0]
    spec = SyncSpec(
        preset=source["source_id"],
        server=source["server"],
        tool=source["tools"][0],
        raw=source["preset"],
    )
    small_pages = spec.model_copy(update={"raw": {**spec.raw, "page_size": 2}})
    adapter = McpToolSourceAdapter.from_sync_spec(
        small_pages,
        connector="archivebox-api",
        mapping_reference="connector:archivebox-api",
        schema_mappings={
            key: SchemaMapping.model_validate(value)
            for key, value in declared["schema_mappings"].items()
        },
    )
    results = await run_source_adapter_suite(
        adapter,
        _sessions(
            lambda: build_enumerated_archivebox_server(
                FakeArchiveBox(archivebox_snapshots(5))
            )
        ),
        _sessions(
            lambda: build_enumerated_archivebox_server(
                FakeArchiveBox([]), malformed=True
            )
        ),
    )
    assert_conformant(results)


async def test_offset_mode_adapter_passes_the_conformance_kit() -> None:
    rows = [
        {"sys_id": f"inc{n}", "sys_updated_on": f"2026-09-0{n} 00:00:00"}
        for n in range(1, 6)
    ]
    adapter = McpToolSourceAdapter(
        ToolPreset.from_mapping("servicenow-incidents", SERVICENOW_STYLE),
        connector="servicenow-api",
        tool_schema_sha256=TABLE_WIRE_SHA256,
        mapping_reference="connector:servicenow-api#mappings/Incident",
    )
    results = await run_source_adapter_suite(
        adapter,
        _sessions(lambda: build_table_server(rows)),
        _sessions(lambda: build_table_server(rows, malformed=True)),
    )
    assert_conformant(results)
