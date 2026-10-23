"""SDK-CONNECTOR-CONTROL-R073: the factory serves packaged content by default."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastmcp import Client

from agent_connector_sdk.mcp.content import ConnectorContent

pytestmark = pytest.mark.spec("SDK-CONNECTOR-CONTROL-R073")

FIXTURE = Path(__file__).parent / "fixture_package"
SERVER = (
    "from agent_connector_sdk.mcp.server import create_mcp_server\n"
    "def build(**kw):\n"
    "    return create_mcp_server('scaffold-mcp', version='1.2.3', command_args=[], **kw)\n"
)


def _scaffold(tmp_path: Path, monkeypatch, *, declared: bool) -> object:
    root = tmp_path / "scaffold_mcp_repo"
    package = root / "scaffold_mcp"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mcp_server.py").write_text(SERVER, encoding="utf-8")
    for directory in ("skills", "prompts", "ontology"):
        shutil.copytree(FIXTURE / directory, package / directory)
    pyproject = '[project]\nname = "scaffold-mcp"\nversion = "1.2.3"\n'
    if declared:
        pyproject += (
            '[project.entry-points."agent_connector_sdk.connector"]\n'
            'scaffold-mcp = "scaffold_mcp"\n'
        )
    (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    monkeypatch.syspath_prepend(str(root))
    for loaded in [m for m in sys.modules if m.split(".")[0] == "scaffold_mcp"]:
        monkeypatch.delitem(sys.modules, loaded)
    import importlib

    return importlib.import_module("scaffold_mcp.mcp_server")


async def test_scaffolded_connector_serves_all_surfaces_without_content(
    tmp_path, monkeypatch
):
    module = _scaffold(tmp_path, monkeypatch, declared=True)
    _, mcp, _ = module.build()
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        prompts = {p.name for p in await client.list_prompts()}
    assert any(u.startswith("skill://") for u in uris)
    assert any(u.startswith("ontology://scaffold-mcp/") for u in uris)
    assert any(u.startswith("shapes://scaffold-mcp/") for u in uris)
    assert "demo_agent" in prompts
    assert "connector-status" in prompts


async def test_explicit_content_overrides_the_default(tmp_path, monkeypatch):
    module = _scaffold(tmp_path, monkeypatch, declared=True)
    explicit = ConnectorContent(
        connector="other-mcp", package_root=FIXTURE, package_version="1.0.0"
    )
    _, mcp, _ = module.build(content=explicit)
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
    assert any(u.startswith("ontology://other-mcp/") for u in uris)
    assert not any(u.startswith("ontology://scaffold-mcp/") for u in uris)


async def test_missing_entry_point_warns_and_serves_tools_only(
    tmp_path, monkeypatch, capsys
):
    module = _scaffold(tmp_path, monkeypatch, declared=False)
    _, mcp, _ = module.build()
    err = capsys.readouterr().err
    assert "agent_connector_sdk.connector" in err and "scaffold_mcp" in err
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
    assert not any(u.startswith(("skill://", "ontology://")) for u in uris)
