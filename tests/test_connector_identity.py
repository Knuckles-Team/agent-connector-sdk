"""SDK-CONNECTOR-CONTROL-R071: one declared connector identity, the fleet name."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from agent_connector_sdk import connector_identity as identity
from agent_connector_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    ConnectorIdentityError,
    connector_name,
    declared_connector_name,
)
from agent_connector_sdk.ingest.model import IngestBinding
from agent_connector_sdk.mcp.content import ConnectorContent, ContentError

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R071")


def _points(*pairs: tuple[str, str]):
    def fake(*, group: str):
        assert group == CONNECTOR_ENTRY_POINT_GROUP
        return [EntryPoint(name, value, group) for name, value in pairs]

    return fake


def test_installed_name_resolves_from_any_module(monkeypatch):
    monkeypatch.setattr(
        identity, "entry_points", _points(("searxng-mcp", "searxng_mcp"), ("x", "y"))
    )
    assert connector_name("searxng_mcp.kg_ingest") == "searxng-mcp"


@pytest.mark.parametrize(
    "pairs",
    [
        (),
        (("a-mcp", "searxng_mcp"), ("b-mcp", "searxng_mcp")),
        (("Bad Name", "searxng_mcp"),),
    ],
)
def test_missing_duplicate_or_invalid_name_refused(monkeypatch, pairs):
    monkeypatch.setattr(identity, "entry_points", _points(*pairs))
    with pytest.raises(ConnectorIdentityError):
        connector_name("searxng_mcp")


def test_pyproject_declaration_reads_statically(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "searxng-api"\n'
        f'[project.entry-points."{CONNECTOR_ENTRY_POINT_GROUP}"]\n'
        'searxng-mcp = "searxng_mcp"\n',
        encoding="utf-8",
    )
    assert declared_connector_name(pyproject) == "searxng-mcp"
    pyproject.write_text('[project]\nname = "searxng-api"\n', encoding="utf-8")
    assert declared_connector_name(pyproject) is None


def test_binding_and_content_take_the_declared_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        identity, "entry_points", _points(("searxng-mcp", "searxng_mcp"))
    )
    (tmp_path / "connector_manifest.yml").write_text(
        "connector: searxng-mcp\n", encoding="utf-8"
    )
    binding = IngestBinding.for_package("searxng_mcp.kg_ingest", stream="searxng")
    content = ConnectorContent.for_package("searxng_mcp", tmp_path, "1.0.0")
    assert binding.connector == content.connector == "searxng-mcp"
    assert content.manifest_path == tmp_path / "connector_manifest.yml"


def test_content_name_disagreeing_with_manifest_is_refused(tmp_path: Path):
    manifest = tmp_path / "connector_manifest.yml"
    manifest.write_text('{"connector": "searxng-mcp"}\n', encoding="utf-8")
    with pytest.raises(ContentError, match="disagrees"):
        ConnectorContent(
            connector="searxng-api",
            package_root=tmp_path,
            package_version="1.0.0",
            manifest_path=manifest,
        )
