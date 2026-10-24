"""SDK-CONNECTOR-CONTROL-R019.1, R071.1, R071.2: the SDK runs a declared connector."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from connector_dist import build
from fastmcp import Client

import agent_connector_sdk
from agent_connector_sdk.connector import (
    Connector,
    build_server,
    content_dirs,
    installed_connectors,
    resolve_connector,
    run,
)
from agent_connector_sdk.connector_identity import (
    ConnectorIdentityError,
    connector_distribution,
    connector_version,
    distribution_version,
)


@pytest.fixture
def democonn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    build(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        monkeypatch.delitem(sys.modules, name)
    yield tmp_path
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        sys.modules.pop(name)


async def _read(mcp):
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        resources = {str(r.uri) for r in await client.list_resources()}
        prompts = {p.name for p in await client.list_prompts()}
    return tools, resources, prompts


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_build_server_registers_tools_and_content_from_the_declaration(
    democonn,
) -> None:
    args, mcp = build_server("democonn", command_args=["--transport", "stdio"])
    tools, resources, prompts = asyncio.run(_read(mcp))
    assert args.transport == "stdio"
    assert mcp.name == "demo-mcp"
    assert any("list_items" in t for t in tools)
    assert "ontology://demo-mcp/demo.ttl" in resources
    assert "connector://resources" in resources
    assert any(u.startswith("skill://") for u in resources)
    assert {"demo", "connector-status"} <= prompts


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_server_version_is_the_metadata_version(democonn) -> None:
    _, mcp = build_server("democonn", command_args=["--transport", "stdio"])
    assert str(mcp.version) == "1.2.3"


class _FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, transport: str, **kwargs) -> None:
        self.calls.append((transport, kwargs))


def _patched(monkeypatch, transport: str) -> _FakeServer:
    from types import SimpleNamespace

    import agent_connector_sdk.connector as module

    fake = _FakeServer()
    args = SimpleNamespace(
        transport=transport, host="127.0.0.1", port=8123, auth_type="none"
    )
    monkeypatch.setattr(
        module, "build_server", lambda package, command_args=None: (args, fake)
    )
    return fake


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_run_serves_network_transports_with_host_and_port(
    democonn, monkeypatch, capsys, transport
) -> None:
    fake = _patched(monkeypatch, transport)
    run("democonn")
    assert fake.calls == [(transport, {"host": "127.0.0.1", "port": 8123})]
    assert "demo-mcp MCP v1.2.3" in capsys.readouterr().err


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_run_refuses_an_unknown_transport(democonn, monkeypatch) -> None:
    fake = _patched(monkeypatch, "carrier-pigeon")
    with pytest.raises(SystemExit) as exit_:
        run("democonn")
    assert exit_.value.code == 1
    assert fake.calls == []


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_run_defaults_to_the_calling_package(democonn, monkeypatch) -> None:
    from fastmcp import FastMCP

    served: list[str | None] = []
    monkeypatch.setattr(
        FastMCP, "run", lambda self, transport=None, **kw: served.append(transport)
    )
    namespace = {"__name__": "democonn.__main__", "run": run}
    exec("run(command_args=['--transport', 'stdio'])", namespace)
    assert served == ["stdio"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_connector_declares_client_and_factory_together() -> None:
    with pytest.raises(ValueError, match="declared together"):
        Connector(api=object)


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R019.1")
def test_package_root_exports_run_and_connector_lazily() -> None:
    assert agent_connector_sdk.run is run
    assert agent_connector_sdk.Connector is Connector
    with pytest.raises(AttributeError):
        agent_connector_sdk.missing  # noqa: B018


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R071.1")
def test_content_is_found_by_convention_with_one_entry_point(democonn) -> None:
    dirs = content_dirs("democonn")
    assert dirs.skills == democonn / "democonn" / "skills"
    assert dirs.ontology.joinpath("demo.ttl").is_file()
    resolved = resolve_connector("democonn")
    assert resolved.name == "demo-mcp"
    assert [c.name for c in installed_connectors() if c.package == "democonn"] == [
        "demo-mcp"
    ]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R071.1")
def test_attribute_must_be_a_connector(tmp_path, monkeypatch) -> None:
    build(tmp_path, init="connector = 5\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "democonn", raising=False)
    with pytest.raises(ConnectorIdentityError, match="must be an"):
        resolve_connector("democonn")


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R071.2")
def test_versions_come_from_package_metadata(democonn) -> None:
    assert connector_version("democonn") == "1.2.3"
    assert connector_distribution("democonn") == "democonn"
    assert (
        distribution_version("agent-connector-sdk") == agent_connector_sdk.__version__
    )
    with pytest.raises(ConnectorIdentityError, match="not installed"):
        distribution_version("no-such-distribution-xyz")


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R071.1")
def test_resolution_returns_typed_values(democonn) -> None:
    from agent_connector_sdk.connector import ConnectorContentDirs, ResolvedConnector
    from agent_connector_sdk.connector_identity import ConnectorPoint, connector_point

    point = connector_point("democonn")
    assert isinstance(point, ConnectorPoint)
    assert (point.name, point.attribute, point.pyproject) == (
        "demo-mcp",
        "connector",
        None,
    )
    resolved = resolve_connector("democonn")
    assert isinstance(resolved, ResolvedConnector)
    assert isinstance(resolved.dirs, ConnectorContentDirs)
