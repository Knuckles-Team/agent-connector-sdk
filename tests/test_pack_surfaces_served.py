"""A live resource listing and its captured pack share one source declaration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from pydantic import BaseModel

from agent_connector_sdk.access_contract import parse_access_contracts
from agent_connector_sdk.artifacts.pack import build_content_pack
from agent_connector_sdk.artifacts.prompts import PromptArtifactKind
from agent_connector_sdk.artifacts.resources import ResourceArtifactKind
from agent_connector_sdk.artifacts.skills import SkillArtifactKind
from agent_connector_sdk.artifacts.tools import ToolArtifactKind
from agent_connector_sdk.mcp.content import ConnectorContent
from agent_connector_sdk.mcp.server import create_mcp_server
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports.mcp import McpTransport


class Widget(BaseModel):
    id: str
    serial_number: str


def _widget_server(tmp_path: Path) -> tuple[Path, Any]:
    ontology = tmp_path / "ontology"
    ontology.mkdir(exist_ok=True)
    (ontology / "widget.ttl").write_text(
        "@prefix : <http://knuckles.team/kg#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<http://example.invalid/widget> a owl:Ontology ; "
        "owl:imports <http://knuckles.team/kg> .\n"
        ":Widget a owl:Class .\n:serialNumber a owl:DatatypeProperty .\n"
    )
    _, server, _ = create_mcp_server(
        "widget-mcp",
        version="1.0.0",
        command_args=[],
        content=ConnectorContent("widget-mcp", tmp_path, "1.0.0"),
    )
    return ontology, server


async def _read_descriptors(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    declaration = json.loads(
        (await client.read_resource("connector://resources"))[0].text
    )
    resource = json.loads(
        (await client.read_resource("data://widget-mcp/widgets"))[0].text
    )
    return declaration, resource


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R074.3")
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R074.4")
@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R074.6")
async def test_factory_serves_and_packs_every_surface_with_a_parseable_contract(
    tmp_path: Path,
) -> None:
    ontology = tmp_path / "ontology"
    ontology.mkdir()
    (ontology / "shapes").mkdir()
    (ontology / "shapes" / "widget.ttl").write_text("@prefix : <urn:widget:> .\n")
    (tmp_path / "skills" / "widget-reader").mkdir(parents=True)
    (tmp_path / "skills" / "widget-reader" / "SKILL.md").write_text(
        "---\nname: widget-reader\ndescription: Read widgets\n---\nRead widgets.\n"
    )
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "widget.json").write_text(
        json.dumps({"instructions": {"core_directive": "Read widgets."}})
    )
    _, server = _widget_server(tmp_path)

    @server.tool(annotations={"readOnlyHint": True})
    def list_widgets(cursor: str | None = None) -> list[Widget]:
        return []

    async with Client(server) as client:
        uris = {str(item.uri) for item in await client.list_resources()}
        assert "data://widget-mcp/widgets" in uris
        assert "ontology://widget-mcp/widget.ttl" in uris
        assert "shapes://widget-mcp/widget.ttl" in uris
        assert "skill://widget-reader/SKILL.md" in uris
        assert any(item.name == "widget" for item in await client.list_prompts())
        assert any(item.name == "list_widgets" for item in await client.list_tools())
        declaration, resource = await _read_descriptors(client)
        assert declaration["descriptors"] == [resource]
        surfaces = declaration["surfaces"]
        assert set(surfaces) == {
            "tools",
            "prompts",
            "skills",
            "ontology",
            "shapes",
            "data",
        }
        assert all(surfaces[name]["count"] >= 1 for name in surfaces)
        assert all(len(surfaces[name]["sha256"]) == 64 for name in surfaces)
        assert surfaces["tools"]["count"] == len(await client.list_tools())
        assert surfaces["prompts"]["count"] == len(await client.list_prompts())
        for scheme, name in (
            ("skill", "skills"),
            ("ontology", "ontology"),
            ("shapes", "shapes"),
            ("data", "data"),
        ):
            assert surfaces[name]["count"] == sum(
                uri.startswith(f"{scheme}://") for uri in uris
            )
        (ontology / "widget.ttl").write_text(
            (ontology / "widget.ttl").read_text() + "\n"
        )
        updated = json.loads(
            (await client.read_resource("connector://resources"))[0].text
        )
        assert (
            updated["surfaces"]["ontology"]["sha256"] != surfaces["ontology"]["sha256"]
        )

    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        pack = await build_content_pack(
            session,
            connector="widget-mcp",
            kinds=(
                ToolArtifactKind(),
                PromptArtifactKind(),
                SkillArtifactKind(),
                ResourceArtifactKind(),
            ),
        )
    entries = {entry.uri: entry for entry in pack.archive.entries}
    assert "data://widget-mcp/widgets" in entries
    assert "ontology://widget-mcp/widget.ttl" in entries
    assert "shapes://widget-mcp/widget.ttl" in entries
    assert "skill://widget-reader/SKILL.md" in entries
    assert any(entry.name == "widget" for entry in entries.values())
    assert any(entry.name == "list_widgets" for entry in entries.values())
    contract = entries["contract://widget-mcp"]
    body = pack.archive.data[
        contract.body.offset : contract.body.offset + contract.body.length
    ]
    (parsed,) = parse_access_contracts(body.decode())
    assert (parsed.source_id, parsed.entity, parsed.operation, parsed.pagination) == (
        "widget-mcp/widgets",
        "widgets",
        "list_widgets",
        "cursor",
    )
    assert (
        "http://knuckles.team/kg#serialNumber",
        "serial_number",
    ) in parsed.predicates


async def test_source_metadata_overrides_live_descriptor(tmp_path: Path) -> None:
    from agent_connector_sdk.ingest.live_declaration import source_meta

    _, server = _widget_server(tmp_path)

    @server.tool(
        annotations={"readOnlyHint": True},
        meta=source_meta(
            source_id="widgets",
            record_type="Widget",
            id_field="serial_number",
            ontology_class="http://knuckles.team/kg#Widget",
            fields={"serial_number": "http://knuckles.team/kg#serialNumber"},
            pagination="page",
            page_param="page",
            page_size_param="per_page",
            page_size=50,
            records_path="items",
        ),
    )
    def list_widgets(page: int = 1, per_page: int = 50) -> list[Widget]:
        return []

    async with Client(server) as client:
        declaration, resource = await _read_descriptors(client)
        assert declaration["descriptors"] == [resource]
        assert resource["origin"] == resource["mapping_status"] == "declared"
        assert resource["key_field"] == "serial_number"
        assert (resource["pagination"], resource["pagination_param"]) == (
            "page",
            "page",
        )
        assert (
            resource["records_path"],
            resource["page_size"],
            resource["page_size_param"],
        ) == ("items", 50, "per_page")
        binding = next(
            field for field in resource["fields"] if field["name"] == "serial_number"
        )
        assert binding["mapping_status"] == "declared"
        assert binding["ontology_property"] == "http://knuckles.team/kg#serialNumber"
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        pack = await build_content_pack(
            session,
            connector="widget-mcp",
            kinds=(ToolArtifactKind(), ResourceArtifactKind()),
        )
    contract = next(
        entry for entry in pack.archive.entries if entry.uri == "contract://widget-mcp"
    )
    body = pack.archive.data[
        contract.body.offset : contract.body.offset + contract.body.length
    ]
    (parsed,) = parse_access_contracts(body.decode())
    assert (parsed.pagination, parsed.pagination_param, parsed.records_path) == (
        "page",
        "page",
        "items",
    )
    assert (parsed.page_size, parsed.page_size_param, parsed.start_page) == (
        50,
        "per_page",
        1,
    )
    assert parsed.completion == "short_page"


def test_contract_renderer_refuses_noncanonical_resource_identity() -> None:
    from agent_connector_sdk.artifacts.source_contract import render_source_contract

    descriptor = {
        "name": "widgets",
        "uri": "data://other/widgets> <urn:evil> <urn:evil>",
        "ontology_class": "http://knuckles.team/kg#Widget",
        "mapping_status": "proposed",
        "operation": "list_widgets",
        "key_field": "id",
        "pagination": "none",
        "origin": "derived",
    }
    with pytest.raises(ValueError, match="RESOURCE_URI_INVALID"):
        render_source_contract("widget-mcp", [descriptor])


def test_contract_renderer_refuses_values_that_cannot_round_trip() -> None:
    from agent_connector_sdk.artifacts.source_contract import render_source_contract

    descriptor = {
        "name": "widgets",
        "uri": "data://widget-mcp/widgets",
        "ontology_class": "http://knuckles.team/kg#Widget",
        "mapping_status": "proposed",
        "operation": "list\nwidgets",
        "key_field": "id",
        "pagination": "none",
        "origin": "derived",
    }
    with pytest.raises(ValueError, match="RESOURCE_CONTRACT_INVALID"):
        render_source_contract("widget-mcp", [descriptor])


def test_each_resource_has_a_distinct_stable_foreign_source_id() -> None:
    from agent_connector_sdk.artifacts.source_contract import render_source_contract

    def descriptor(name: str) -> dict[str, object]:
        return {
            "name": name,
            "uri": f"data://widget-mcp/{name}",
            "ontology_class": "http://knuckles.team/kg#Widget",
            "mapping_status": "proposed",
            "operation": f"list_{name}",
            "key_field": "id",
            "pagination": "none",
            "origin": "derived",
        }

    values = [descriptor("widgets"), descriptor("gadgets")]
    text = render_source_contract("widget-mcp", values)
    assert text == render_source_contract("widget-mcp", list(reversed(values)))
    assert {item.source_id for item in parse_access_contracts(text)} == {
        "widget-mcp/gadgets",
        "widget-mcp/widgets",
    }


@pytest.mark.parametrize(
    ("mode", "extra"),
    [
        (
            "cursor",
            {
                "pagination_param": "cursor",
                "next_cursor_path": "next",
                "completion": "cursor_null",
            },
        ),
        (
            "offset",
            {
                "pagination_param": "offset",
                "page_size": 50,
                "page_size_param": "limit",
                "completion": "short_page",
                "start_offset": 10,
            },
        ),
    ],
)
def test_paging_and_result_declarations_round_trip(
    mode: str, extra: dict[str, object]
) -> None:
    from agent_connector_sdk.artifacts.source_contract import render_source_contract

    descriptor = {
        "name": "widgets",
        "uri": "data://widget-mcp/widgets",
        "ontology_class": "http://knuckles.team/kg#Widget",
        "mapping_status": "declared",
        "operation": "list_widgets",
        "key_field": "id",
        "pagination": mode,
        "origin": "declared",
        "records_path": "data.items",
        **extra,
    }
    (contract,) = parse_access_contracts(
        render_source_contract("widget-mcp", [descriptor])
    )
    assert contract.pagination == mode and contract.records_path == "data.items"
    for name, value in extra.items():
        assert getattr(contract, name) == value
