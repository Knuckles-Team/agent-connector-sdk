"""SCION-CONNECTOR-CONTROL-R071: one declared connector identity, the fleet name."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from scion_sdk import connector_identity as identity
from scion_sdk.connector_identity import (
    CONNECTOR_ENTRY_POINT_GROUP,
    ConnectorIdentityError,
    connector_name,
    declared_connector_name,
)
from scion_sdk.ingest.model import IngestBinding
from scion_sdk.mcp.content import ConnectorContent

pytestmark = pytest.mark.spec("SCION-CONNECTOR-CONTROL-R071")


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
    binding = IngestBinding.for_package("searxng_mcp.kg_ingest", stream="searxng")
    content = ConnectorContent.for_package("searxng_mcp", tmp_path, "1.0.0")
    assert binding.connector == content.connector == "searxng-mcp"


def test_uninstalled_source_checkout_reads_its_pyproject(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(identity, "entry_points", _points())
    package = tmp_path / "checkout_only_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "checkout-only"\n'
        f'[project.entry-points."{CONNECTOR_ENTRY_POINT_GROUP}"]\n'
        'checkout-only-mcp = "checkout_only_pkg"\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert connector_name("checkout_only_pkg.kg_ingest") == "checkout-only-mcp"
