"""SCION-SOURCE-INGEST-R004.29: declarations are typed data the SDK reads."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from connector_dist import build

from agent_connector_sdk.ingest import DeclarationError, load_declaration
from agent_connector_sdk.ingest.live_declaration import expand_field_sets

V1 = """\
from agent_connector_sdk.ingest.live_declaration import source_meta

SOURCES = (source_meta(tool="demo_list_items", source_id="demo-items", record_type="DemoItem", id_field="id"),)
SCHEMA_MAPPINGS = {"DemoItem": {"ontology_class": "DemoItem", "fields": {"name": "xsd:string"}}}
RESOURCES = ()
"""


def _load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    build(tmp_path, **kwargs)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        monkeypatch.delitem(sys.modules, name)
    try:
        return load_declaration("democonn")
    finally:
        for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
            sys.modules.pop(name)


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_shared_field_sets_expand_once_per_mapping(tmp_path, monkeypatch) -> None:
    declaration = _load(tmp_path, monkeypatch)
    assert declaration.connector == "demo-mcp"
    assert [s.source_id for s in declaration.sources] == ["demo-items"]
    item = declaration.schema_mappings["DemoItem"].fields
    assert item == {"name": "xsd:string", "created": "xsd:dateTime", "size": "xsd:long"}
    assert declaration.schema_mappings["DemoLeaf"].fields == {
        "name": "xsd:string",
        "created": "xsd:dateTime",
    }


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_previous_schema_version_still_reads(tmp_path, monkeypatch) -> None:
    declaration = _load(tmp_path, monkeypatch, sources=V1)
    assert declaration.schema_mappings["DemoItem"].fields == {"name": "xsd:string"}


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_inline_fields_win_over_a_shared_set() -> None:
    merged = expand_field_sets(
        {"field_sets": ["a"], "fields": {"x": "xsd:long"}},
        {"a": {"x": "xsd:string", "y": "xsd:int"}},
    )
    assert merged == {"fields": {"x": "xsd:long", "y": "xsd:int"}}


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_unknown_field_set_and_unsupported_version_are_refused(
    tmp_path, monkeypatch
) -> None:
    with pytest.raises(DeclarationError, match="unknown field set"):
        expand_field_sets({"field_sets": ["nope"]}, {})
    with pytest.raises(DeclarationError, match="SCHEMA_VERSION"):
        _load(tmp_path, monkeypatch, sources="SCHEMA_VERSION = 3\n")


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_a_package_without_sources_is_refused(tmp_path, monkeypatch) -> None:
    with pytest.raises(DeclarationError, match="ships no connector_sources"):
        _load(tmp_path, monkeypatch, sources=None)


@pytest.mark.spec("SCION-SOURCE-INGEST-R004.29")
def test_reader_accepts_schema_versions_one_and_two() -> None:
    from agent_connector_sdk.ingest.live_declaration import DECLARATION_SCHEMA_VERSIONS

    assert DECLARATION_SCHEMA_VERSIONS == (1, 2)
