"""The MCP server is the only place connector metadata is read from (SDK-CONNECTOR-CONTROL-R075)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from fastmcp import Client, FastMCP

from agent_connector_sdk.certify.certification import certify_connector
from agent_connector_sdk.certify.checkout import checkout_from_resources
from agent_connector_sdk.ingest.live_declaration import (
    META_KEY,
    RESOURCES_URI,
    build_declaration,
    register_live_declaration,
    source_meta,
)
from agent_connector_sdk.manifest.declaration import (
    ContractError,
    SyncContract,
    contract_from_declaration,
    contract_from_document,
)
from agent_connector_sdk.mcp.content import PROMPT_META_KEY, _register_prompt
from agent_connector_sdk.mcp.tool_surface import registered_tools
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.descriptors import ConnectorDescriptor, EndpointSpec
from agent_connector_sdk.runner.errors import RunnerConfigurationError
from agent_connector_sdk.runner.plans import load_sync_adapters
from agent_connector_sdk.transports.mcp import McpTransport

FIXTURE = Path(__file__).parent / "fixture_package"


def _server(connector: str = "demo-mcp") -> FastMCP:
    mcp = FastMCP("demo-mcp")

    @mcp.tool(
        meta=source_meta(
            source_id="demo",
            record_type="DemoItem",
            id_field="id",
            title_field="title",
            cursor_field="published",
            records_path="items",
            ontology_class="demo:Item",
            fields={"title": "demo:title"},
            preset={
                "pagination": "cursor",
                "cursor_param": "c",
                "cursor_path": "c",
                "params_style": "args",
            },
        )
    )
    def demo_reader(c: str = "") -> dict:
        """Read items."""
        return {"items": []}

    register_live_declaration(mcp, connector)
    return mcp


def _descriptor(connector: str = "demo-mcp") -> ConnectorDescriptor:
    return ConnectorDescriptor(
        connector=connector, endpoint=EndpointSpec(url="http://127.0.0.1:1/mcp")
    )


class _LiveSession:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def read_resource(self, uri: str) -> str:
        (part,) = await self._client.read_resource(uri)
        return part.text


# spec: SDK-CONNECTOR-CONTROL-R075
# spec: SDK-CONNECTOR-CONTROL-R075.2
@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R075.3")
def test_server_serves_declaration_live_and_runner_reads_only_that() -> None:
    async def run() -> None:
        async with Client(_server()) as client:
            tools = await client.list_tools()
            assert tools[0].meta is not None
            assert META_KEY in tools[0].meta
            adapters = await load_sync_adapters(_descriptor(), _LiveSession(client))  # type: ignore[arg-type]
            assert list(adapters) == ["demo"]
            uris = {str(r.uri) for r in await client.list_resources()}
            assert uris == {RESOURCES_URI}

    anyio.run(run)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R075.3")
def test_declared_connector_must_match_descriptor() -> None:
    async def run() -> None:
        async with Client(_server("other-mcp")) as client:
            with pytest.raises(RunnerConfigurationError, match="other-mcp"):
                await load_sync_adapters(_descriptor(), _LiveSession(client))  # type: ignore[arg-type]

    anyio.run(run)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R075.3")
def test_server_without_a_sync_preset_is_refused() -> None:
    mcp = FastMCP("demo-mcp")
    register_live_declaration(mcp, "demo-mcp")

    async def run() -> None:
        async with Client(mcp) as client:
            with pytest.raises(RunnerConfigurationError, match="no sync preset"):
                await load_sync_adapters(_descriptor(), _LiveSession(client))  # type: ignore[arg-type]

    anyio.run(run)


def test_invalid_declaration_is_refused() -> None:
    with pytest.raises(ContractError):
        contract_from_document("{}")
    bad = {
        "connector": "demo-mcp",
        "sources": [
            {
                "source_id": "demo",
                "record_type": "T",
                "tools": ["t"],
                "id_field": "id",
                "preset": {"pagination": "bogus"},
            }
        ],
    }
    with pytest.raises(ContractError):
        contract_from_declaration(
            __import__(
                "agent_connector_sdk.ingest.sources", fromlist=["x"]
            ).IngestSourceDeclaration.model_validate(bad)
        )


def test_build_declaration_maps_meta_without_any_file() -> None:
    declaration = build_declaration("demo-mcp", registered_tools(_server()).values())
    assert declaration.sources[0].tools == ("demo_reader",)
    assert declaration.schema_mappings["DemoItem"].ontology_class == "demo:Item"
    contract = contract_from_declaration(declaration)
    assert isinstance(contract, SyncContract)
    again = contract_from_document(declaration.model_dump_json(exclude_unset=True))
    assert again is not None and again.sync == contract.sync
    assert source_meta(source_id="s", record_type="T", id_field="id").keys() == {
        META_KEY
    }


class _Transport:
    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    def session(self, endpoint: object) -> Any:
        return McpTransport().session(TransportEndpoint(in_process=self._mcp))


def test_certify_reads_the_declaration_and_checks_tools_live() -> None:
    async def run() -> None:
        report = await certify_connector(
            _Transport(_server()),  # type: ignore[arg-type]
            endpoint=None,  # type: ignore[arg-type]
            timeout_seconds=10,
        )
        assert report.listed is True
        assert report.connector == "demo-mcp"
        assert report.passed is True

    anyio.run(run)


def test_checkout_names_exactly_one_server() -> None:
    declaration = build_declaration("demo-mcp", registered_tools(_server()).values())
    checkout = checkout_from_resources(declaration.model_dump_json())
    assert checkout.tools == ("demo_reader",)
    assert checkout.presets_for("demo_reader") == ("demo",)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R075.4")
def test_prompt_serves_its_directive_and_carries_metadata_over_mcp(
    tmp_path: Path,
) -> None:
    path = tmp_path / "specialist.json"
    path.write_text(
        json.dumps(
            {
                "description": "Reads demo items.",
                "prompt_version": "0.2.0",
                "extends": "anything:base",
                "compose": "append",
                "metadata": {"topic": "Demo", "tone": "plain"},
                "identity": {"role": "Demo Specialist", "goal": "Read items."},
                "serves": "demo:Item",
                "instructions": {"core_directive": "Read the demo stream."},
            }
        ),
        encoding="utf-8",
    )
    mcp = FastMCP("demo-mcp")
    _register_prompt(mcp, path)

    async def run() -> None:
        async with Client(mcp) as client:
            (prompt,) = await client.list_prompts()
            assert prompt.title == "Demo Specialist"
            meta = (prompt.meta or {})[PROMPT_META_KEY]
            assert meta["topic"] == "Demo"
            assert meta["version"] == "0.2.0"
            assert meta["systemPromptFor"] == "demo:Item"
            assert "extends" not in meta
            result = await client.get_prompt("specialist")
            assert result.messages[0].content.text == "Read the demo stream."

    anyio.run(run)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R075.5")
def test_skill_directory_name_matches_frontmatter_name() -> None:
    for skill in sorted((FIXTURE / "skills").glob("*/SKILL.md")):
        front = yaml.safe_load(skill.read_text(encoding="utf-8").split("---")[1])
        assert front["name"] == skill.parent.name


def test_connector_sources_module_declares_by_tool_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_connector_sdk.ingest.live_declaration import (
        SOURCES_MODULE,
        load_sources_module,
    )

    pkg = tmp_path / "demopkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "connector_sources.py").write_text(
        "from agent_connector_sdk.ingest.live_declaration import source_meta\n"
        "SOURCES = (source_meta(tool='demo_reader', source_id='by-name',"
        " record_type='Thing', id_field='id', ontology_class='demo:Thing'),)\n"
        "SCHEMA_MAPPINGS = {'Other': {'ontology_class': 'demo:Other', 'fields': {}}}\n"
        "RESOURCES = ({'name': 'Thing', 'id_prefix': 'thing'},)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    declared = load_sources_module(pkg)
    assert declared is not None
    tools = registered_tools(_server()).values()
    declaration = build_declaration("demo-mcp", tools, (), declared)
    by_name = declaration.source("by-name")
    assert by_name is not None and by_name.tools == ("demo_reader",)
    assert declaration.schema_mappings["Thing"].ontology_class == "demo:Thing"
    assert "Other" in declaration.schema_mappings
    assert declaration.resources[0].id_prefix == "thing"
    assert load_sources_module(tmp_path / "absent") is None
    assert SOURCES_MODULE == "connector_sources"
    with pytest.raises(ValueError, match="unknown tool"):
        build_declaration(
            "demo-mcp",
            tools,
            (),
            {"SOURCES": ({"connector_sources": [{"tool": "nope"}]},)},
        )
