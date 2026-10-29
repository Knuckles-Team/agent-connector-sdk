"""SCION-CONNECTOR-CONTROL-R074: default data-resource declarations."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from pydantic import BaseModel

from agent_connector_sdk.artifacts.pack import build_connector_content_pack
from agent_connector_sdk.artifacts.resource_derivation import (
    OntologyTerms,
    derive_descriptors,
    scan_ontology,
)
from agent_connector_sdk.artifacts.resource_descriptor import (
    RESOURCES_URI,
    FieldBinding,
    ResourceDeclarationError,
    ResourceDescriptor,
    check_declarations,
    merge_declarations,
    render_resources_document,
)
from agent_connector_sdk.mcp.content import ConnectorContent

pytestmark = pytest.mark.spec("SCION-CONNECTOR-CONTROL-R074.7")

GITHUB = Path(__file__).parent / "fixtures" / "github_agent"
KG = "http://knuckles.team/kg#"
SERVER = (
    "from pathlib import Path\n"
    "from agent_connector_sdk.mcp.content import ConnectorContent\n"
    "from agent_connector_sdk.mcp.server import create_mcp_server\n"
    "def build(**kw):\n"
    "    kw.setdefault('content', ConnectorContent('scaffold-mcp', Path(__file__).parent, '1.2.3'))\n"
    "    return create_mcp_server('scaffold-mcp', version='1.2.3', command_args=[], **kw)\n"
)
ONTOLOGY = """@prefix : <http://knuckles.team/kg#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.invalid/scaffold> a owl:Ontology ; owl:imports <http://knuckles.team/kg> .
:Widget a owl:Class .
:serialNumber a owl:DatatypeProperty .
"""


class Widget(BaseModel):
    id: str
    serial_number: str
    colour: str


def _github_tools() -> list[SimpleNamespace]:
    document = json.loads((GITHUB / "repos_tools.json").read_text(encoding="utf-8"))
    return [
        SimpleNamespace(
            name=t["name"],
            parameters=t["parameters"],
            output_schema=t["output_schema"],
            annotations=SimpleNamespace(**t["annotations"]),
        )
        for t in document["tools"]
    ]


def _github_terms():
    return scan_ontology([(GITHUB / "github.ttl").read_text(encoding="utf-8")])


def test_real_connector_repos_list_yields_a_proposed_resource():
    (repos,) = derive_descriptors("github-agent", _github_tools(), _github_terms())
    assert repos.name == "repositories"
    assert repos.operation == "get_repositories"
    assert repos.get_operation == "get_repository"
    assert repos.key_field == "id"
    assert (repos.pagination, repos.pagination_param) == ("page", "page")
    assert repos.access_kind == "mcp_tool"
    assert repos.ontology_class == KG + "Repository"
    assert repos.mapping_status == "proposed"
    by_name = {f.name: f for f in repos.fields}
    assert set(by_name) == {
        "id",
        "name",
        "full_name",
        "html_url",
        "default_branch",
        "private",
    }
    assert by_name["full_name"].ontology_property == KG + "fullName"
    assert by_name["full_name"].mapping_status == "proposed"
    assert by_name["name"].mapping_status == "unmapped"


def test_derivation_never_approves_and_skips_writes():
    descriptors = derive_descriptors("github-agent", _github_tools(), _github_terms())
    assert all("delete" not in d.operation for d in descriptors)
    statuses = {d.mapping_status for d in descriptors}
    statuses |= {f.mapping_status for d in descriptors for f in d.fields}
    assert statuses <= {"proposed", "unmapped"}
    assert "approved" not in statuses


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"cursor": {}}, ("cursor", "cursor")),
        ({"next_url": {}}, ("cursor", "next_url")),
        ({"offset": {}, "limit": {}}, ("offset", "offset")),
        ({"page": {}}, ("page", "page")),
        ({"q": {}}, ("none", None)),
    ],
)
def test_pagination_mode_is_detected_from_parameters(params, expected):
    tool = SimpleNamespace(
        name="list_things",
        parameters={"type": "object", "properties": params},
        output_schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                    },
                }
            },
        },
        annotations=SimpleNamespace(readOnlyHint=True),
    )
    (thing,) = derive_descriptors("x", [tool], scan_ontology([]))
    assert (thing.pagination, thing.pagination_param) == expected
    assert thing.ontology_class is None and thing.mapping_status == "unmapped"


def test_explicit_declaration_overrides_the_default():
    derived = derive_descriptors("github-agent", _github_tools(), _github_terms())
    declared = [
        {
            "name": "repositories",
            "ontology_class": KG + "Organization",
            "pagination": "cursor",
            "owner": "platform",
        }
    ]
    (merged,) = merge_declarations(
        "github-agent", derived, declared, _github_terms().class_iris
    )
    assert merged.origin == "declared" and merged.mapping_status == "declared"
    assert merged.ontology_class == KG + "Organization"
    assert merged.pagination == "cursor" and merged.owner == "platform"
    assert merged.operation == "get_repositories"


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"ontology_class": KG + "Nope"}, "RESOURCE_UNMAPPED"),
        ({"access_kind": "carrier_pigeon"}, "ACCESS_KIND_UNKNOWN"),
        ({"pagination": "sometimes"}, "PAGINATION_UNDECLARED"),
        ({"credential_ref": "hunter2"}, "SECRET_IN_CONTRACT"),
    ],
)
def test_declarations_are_refused_with_a_named_code(override, code):
    derived = derive_descriptors("github-agent", _github_tools(), _github_terms())
    declared = [{"name": "repositories", **override}]
    with pytest.raises(ResourceDeclarationError) as raised:
        merge_declarations(
            "github-agent", derived, declared, _github_terms().class_iris
        )
    assert raised.value.code == code


def _scaffold(tmp_path: Path, monkeypatch):
    root = tmp_path / "scaffold_mcp_repo"
    package = root / "scaffold_mcp"
    (package / "ontology").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mcp_server.py").write_text(SERVER, encoding="utf-8")
    (package / "ontology" / "scaffold.ttl").write_text(ONTOLOGY, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "scaffold-mcp"\nversion = "1.2.3"\n'
        '[project.entry-points."agent_connector_sdk.connector"]\n'
        'scaffold-mcp = "scaffold_mcp"\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(root))
    for loaded in [m for m in sys.modules if m.split(".")[0] == "scaffold_mcp"]:
        monkeypatch.delitem(sys.modules, loaded)
    return importlib.import_module("scaffold_mcp.mcp_server")


def _add_widget_tool(mcp) -> None:
    @mcp.tool(annotations={"readOnlyHint": True})
    def list_widgets(cursor: str | None = None) -> list[Widget]:
        """List widgets."""
        return []


async def _read_resources(mcp) -> dict:
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert RESOURCES_URI in uris
        parts = await client.read_resource(RESOURCES_URI)
    return json.loads(parts[0].text)


async def test_scaffolded_connector_serves_derived_resources(tmp_path, monkeypatch):
    module = _scaffold(tmp_path, monkeypatch)
    _, mcp, _ = module.build()
    _add_widget_tool(mcp)
    document = await _read_resources(mcp)
    (widget,) = document["descriptors"]
    assert document["connector"] == "scaffold-mcp"
    assert widget["uri"] == "data://scaffold-mcp/widgets"
    assert widget["operation"] == "list_widgets"
    assert widget["pagination"] == "cursor" and widget["key_field"] == "id"
    assert widget["ontology_class"] == KG + "Widget"
    assert widget["mapping_status"] == "proposed" and widget["origin"] == "derived"
    serial = next(f for f in widget["fields"] if f["name"] == "serial_number")
    assert serial["ontology_property"] == KG + "serialNumber"
    assert serial["mapping_status"] == "proposed"


async def test_pack_carries_the_resource_declarations(tmp_path):
    root = tmp_path / "pkg"
    (root / "ontology").mkdir(parents=True)
    (root / "ontology" / "scaffold.ttl").write_text(ONTOLOGY, encoding="utf-8")
    content = ConnectorContent(
        connector="scaffold-mcp", package_root=root, package_version="1.0.0"
    )
    captured = await build_connector_content_pack(content)
    assert RESOURCES_URI in captured.resource_uris


def test_descriptor_renders_and_declarations_load_and_check(tmp_path):
    descriptor = ResourceDescriptor(
        name="widgets",
        uri="data://x/widgets",
        ontology_class=KG + "Widget",
        mapping_status="declared",
        operation="list_widgets",
        key_field="id",
        pagination="none",
        origin="declared",
        fields=(FieldBinding(name="id"),),
    )
    document = json.loads(render_resources_document("x", (descriptor,)))
    assert document["descriptors"][0]["fields"][0]["mapping_status"] == "unmapped"
    terms = OntologyTerms(classes={"widget": KG + "Widget"}, properties={})
    check_declarations(
        [{"name": "widgets", "ontology_class": KG + "Widget"}], terms.class_iris
    )
    with pytest.raises(ResourceDeclarationError):
        check_declarations(
            [{"name": "w", "ontology_class": "urn:no"}], terms.class_iris
        )
