"""SDK-CONNECTOR-CONTROL-R019.2, R019.3: typed bootstrap hooks and config mounts."""

from __future__ import annotations

import asyncio
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any, Literal

import pytest
from connector_dist import build
from fastmcp import Client, FastMCP
from fastmcp.tools import tool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient

from agent_connector_sdk.config_mounts import (
    CONFIG_MOUNTS_SCHEMA,
    CONFIG_ROOT,
    ConfigMount,
    ConfigMountError,
    config_mounts,
)
from agent_connector_sdk.connector import (
    Connector,
    build_server,
    content_dirs,
    resolve_connector,
)
from agent_connector_sdk.connector_hooks import (
    Readiness,
    RegistrationContext,
    Route,
)
from agent_connector_sdk.mcp.action_split import split_action_tool
from agent_connector_sdk.testing.conformance import ConformanceFailure, run_check

R2 = "SDK-CONNECTOR-CONTROL-R019.2"
R3 = "SDK-CONNECTOR-CONTROL-R019.3"


@pytest.fixture
def democonn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    build(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        monkeypatch.delitem(sys.modules, name)
    yield tmp_path
    for name in [m for m in sys.modules if m.split(".")[0] == "democonn"]:
        sys.modules.pop(name)


def _declare(monkeypatch: pytest.MonkeyPatch, connector: Connector) -> None:
    import democonn

    monkeypatch.setattr(democonn, "connector", connector)


def _server(monkeypatch: pytest.MonkeyPatch, connector: Connector) -> Any:
    _declare(monkeypatch, connector)
    return build_server("democonn", command_args=["--transport", "stdio"])[1]


def _tools(mcp: Any) -> set[str]:
    async def read() -> set[str]:
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

    return asyncio.run(read())


def register_shared_tools(mcp: FastMCP[object]) -> None:
    @mcp.tool(name="demo_shared")
    def shared() -> str:
        """Shared."""
        return "shared"


def register_router_tools(mcp: FastMCP[object]) -> None:
    @mcp.tool(name="demo_router")
    def router(action: Literal["status", "purge"], target: str = "") -> str:
        """Route an action."""
        return f"{action} {target}"


# --- tool_registry --------------------------------------------------------------------------------
@pytest.mark.spec(R2)
def test_tool_registry_uses_the_declared_tag_and_toggle(democonn, monkeypatch) -> None:
    entry = ("shared", "SHAREDTOOL", register_shared_tools)
    mcp = _server(monkeypatch, Connector(tool_registry=(entry,)))
    assert "demo_shared" in _tools(mcp)
    monkeypatch.setenv("SHAREDTOOL", "false")
    assert "demo_shared" not in _tools(
        _server(monkeypatch, Connector(tool_registry=(entry,)))
    )


@pytest.mark.spec(R2)
def test_tool_registry_and_tools_are_exclusive() -> None:
    with pytest.raises(ValueError, match="not both"):
        Connector(
            tools="democonn.tools",
            tool_registry=(("s", "STOOL", register_shared_tools),),
        )


# --- action_tools ---------------------------------------------------------------------------------
@pytest.mark.spec(R2)
def test_action_tools_split_with_declared_prefix_without_a_client(
    democonn, monkeypatch
) -> None:
    connector = Connector(
        action_tools=(("router", "ROUTERTOOL", register_router_tools),),
        action_prefixes={"demo_router": "dr"},
    )
    tools = _tools(_server(monkeypatch, connector))
    assert {"dr_status", "dr_purge"} <= tools
    assert "demo_router" not in tools


@pytest.mark.spec(R2)
def test_action_tools_default_prefix_and_toggle(democonn, monkeypatch) -> None:
    connector = Connector(
        action_tools=(("router", "ROUTERTOOL", register_router_tools),)
    )
    assert {"demo_router_status", "demo_router_purge"} <= _tools(
        _server(monkeypatch, connector)
    )
    monkeypatch.setenv("ROUTERTOOL", "false")
    assert not {t for t in _tools(_server(monkeypatch, connector)) if "router" in t}


@pytest.mark.spec(R2)
def test_action_prefixes_need_action_tools() -> None:
    with pytest.raises(ValueError, match="action_tools"):
        Connector(action_prefixes={"x": "y"})


@pytest.mark.spec(R2)
def test_split_action_tool_takes_a_prefix() -> None:
    mcp: FastMCP[Any] = FastMCP("split")
    register_router_tools(mcp)
    routed = asyncio.run(mcp.local_provider.list_tools())[0]
    added = split_action_tool(mcp, "demo_router", routed, operations={}, prefix="p")
    assert sorted(added) == ["p_purge", "p_status"]


# --- inline_tools ---------------------------------------------------------------------------------
@tool(name="demo_inline_decorated", tags={"inline"})
async def inline_decorated(query: str) -> str:
    """Decorated inline tool."""
    return query


def inline_plain() -> str:
    """Plain inline tool."""
    return "plain"


@pytest.mark.spec(R2)
def test_inline_tools_are_added_through_fastmcp(democonn, monkeypatch) -> None:
    from democonn.client import Api, get_client

    connector = Connector(
        api=Api, get_client=get_client, inline_tools=(inline_decorated, inline_plain)
    )
    tools = _tools(_server(monkeypatch, connector))
    assert {"demo_inline_decorated", "inline_plain"} <= tools
    assert any("list_items" in t for t in tools)


# --- routes and readiness -------------------------------------------------------------------------
async def _version(_request: Request) -> Response:
    return PlainTextResponse("v")


@pytest.mark.spec(R2)
def test_routes_are_served_through_custom_route(democonn, monkeypatch) -> None:
    mcp = _server(
        monkeypatch,
        Connector(routes=(Route("/version", _version, methods=("GET", "HEAD")),)),
    )
    with TestClient(mcp.http_app()) as client:
        assert client.get("/version").text == "v"
        assert client.get("/health").status_code == 200


@pytest.mark.spec(R2)
@pytest.mark.parametrize("path", ["/health", "/ready", "/ready/", "relative"])
def test_routes_refuse_reserved_and_relative_paths(path: str) -> None:
    with pytest.raises(ValueError):
        Route(path, _version)


@pytest.mark.spec(R2)
def test_routes_refuse_a_duplicate_path_and_method(democonn, monkeypatch) -> None:
    with pytest.raises(ValueError, match="declared twice"):
        _server(
            monkeypatch,
            Connector(routes=(Route("/v", _version), Route("/v", _version))),
        )


async def _ready() -> Readiness:
    return Readiness(True, {"backend": "reachable", "topics": 3})


async def _down() -> Readiness:
    return Readiness(False, {"backend": "unreachable"})


async def _boom() -> Readiness:
    raise ConnectionError("token=secret-value refused")


@pytest.mark.spec(R2)
@pytest.mark.parametrize(
    ("probe", "code", "body"),
    [
        (_ready, 200, {"status": "ready", "backend": "reachable", "topics": 3}),
        (_down, 503, {"status": "unavailable", "backend": "unreachable"}),
        (_boom, 503, {"status": "unavailable", "error": "ConnectionError"}),
    ],
)
def test_readiness_probe_is_served_at_ready(
    democonn, monkeypatch, probe, code, body
) -> None:
    mcp = _server(monkeypatch, Connector(readiness=probe))
    with TestClient(mcp.http_app()) as client:
        response = client.get("/ready")
        assert client.get("/health").json() == {"status": "ok"}
    assert response.status_code == code
    assert response.json() == body
    assert "secret-value" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.spec(R2)
def test_no_ready_route_without_a_probe(democonn, monkeypatch) -> None:
    mcp = _server(monkeypatch, Connector())
    with TestClient(mcp.http_app()) as client:
        assert client.get("/ready").status_code == 404


# --- extra_registrations --------------------------------------------------------------------------
@pytest.mark.spec(R2)
def test_extra_registrations_receive_the_registration_context(
    democonn, monkeypatch
) -> None:
    from democonn.client import Api, get_client

    seen: list[RegistrationContext] = []

    def register(context: RegistrationContext) -> None:
        seen.append(context)
        context.server.tool(name="demo_ctx")(lambda: context.name)

    mcp = _server(
        monkeypatch,
        Connector(api=Api, get_client=get_client, extra_registrations=(register,)),
    )
    (context,) = seen
    assert context.server is mcp
    assert (context.name, context.version) == ("demo-mcp", "1.2.3")
    assert context.settings.transport == "stdio"
    assert context.client_factory is get_client
    assert context.auth is mcp.auth
    assert "demo_ctx" in _tools(mcp)


# --- content_root ---------------------------------------------------------------------------------
@pytest.mark.spec(R2)
def test_content_root_moves_the_content_directories(democonn, monkeypatch) -> None:
    pkg = democonn / "democonn"
    (pkg / "assets").mkdir()
    for kind in ("skills", "prompts", "ontology"):
        shutil.move(pkg / kind, pkg / "assets" / kind)
    _declare(monkeypatch, Connector(content_root="assets"))
    resolved = resolve_connector("democonn")
    assert resolved.dirs.root == pkg
    assert resolved.dirs.content == pkg / "assets"
    assert resolved.dirs.ontology == pkg / "assets" / "ontology"
    _, mcp = build_server("democonn", command_args=["--transport", "stdio"])

    async def resources() -> set[str]:
        async with Client(mcp) as client:
            return {str(r.uri) for r in await client.list_resources()}

    assert "ontology://demo-mcp/demo.ttl" in asyncio.run(resources())


@pytest.mark.spec(R2)
@pytest.mark.parametrize("root", ["", "/abs", "../outside", "a/../../b"])
def test_content_root_must_stay_inside_the_package(root: str) -> None:
    with pytest.raises(ValueError, match="inside the package"):
        Connector(content_root=root)


@pytest.mark.spec(R2)
def test_content_dirs_default_is_the_package_root(democonn) -> None:
    dirs = content_dirs("democonn")
    assert dirs.content == dirs.root


# --- config mounts --------------------------------------------------------------------------------
def _pyproject(mounts: str) -> dict[str, object]:
    return tomllib.loads(f"[tool.pipelines.container]\n{mounts}\n")


@pytest.mark.spec(R3)
def test_config_mounts_parse_interpolated_and_absolute_sources() -> None:
    mounts = config_mounts(
        _pyproject(
            'config_mounts = [{source = "${CONNECTOR_CONFIG_DIR:?set-it}", '
            'target = "/etc/connector"}, {source = "${AGENT_CONFIG_DIR:-/etc/sdk}", '
            'target = "/etc/agent-connector-sdk"}, {source = "/srv/conf", target = "/etc/x"}]'
        )
    )
    assert mounts == (
        ConfigMount("${CONNECTOR_CONFIG_DIR:?set-it}", "/etc/connector"),
        ConfigMount("${AGENT_CONFIG_DIR:-/etc/sdk}", "/etc/agent-connector-sdk"),
        ConfigMount("/srv/conf", "/etc/x"),
    )
    assert config_mounts({}) == ()


@pytest.mark.spec(R3)
@pytest.mark.parametrize(
    "mounts",
    [
        'config_mounts = "x"',
        'config_mounts = [{source = "relative", target = "/etc/x"}]',
        'config_mounts = [{source = "/a/../b", target = "/etc/x"}]',
        'config_mounts = [{source = "/a", target = "etc/x"}]',
        'config_mounts = [{source = "/a", target = "/etc/../x"}]',
        'config_mounts = [{source = "/a", target = "/etc"}]',
        'config_mounts = [{source = "/a", target = "/var/lib/x"}]',
        'config_mounts = [{source = "/a", target = "/etc/x", read_only = false}]',
        'config_mounts = [{source = 1, target = "/etc/x"}]',
        'config_mounts = [{source = "/a", target = "/etc/x"}, {source = "/b", target = "/etc/x"}]',
    ],
)
def test_config_mounts_refuse_malformed_and_unsafe_entries(mounts: str) -> None:
    with pytest.raises(ConfigMountError):
        config_mounts(_pyproject(mounts))


@pytest.mark.spec(R3)
def test_config_mounts_schema_requires_exactly_source_and_target() -> None:
    items = CONFIG_MOUNTS_SCHEMA["items"]
    assert isinstance(items, dict)
    assert items["required"] == ["source", "target"]
    assert items["additionalProperties"] is False
    assert str(CONFIG_ROOT) == "/etc"


@pytest.mark.spec(R3)
def test_conformance_check_fails_an_unsafe_config_mount(democonn) -> None:
    resolved = resolve_connector("democonn")
    run_check("config_mounts", resolved)
    pyproject = democonn / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text()
        + '\n[tool.pipelines.container]\nconfig_mounts = [{source = "/a", target = "/"}]\n'
    )
    with pytest.raises(ConformanceFailure, match="config_mounts"):
        run_check("config_mounts", resolved)


# --- the hook helpers, used directly ---------------------------------------------------------------
@pytest.mark.spec(R2)
def test_hook_helpers_serve_on_a_plain_server() -> None:
    from agent_connector_sdk.connector_hooks import (
        READINESS_PATH,
        RESERVED_PATHS,
        InlineTool,
        ReadinessProbe,
        ReadinessValue,
        Registration,
        ServerRegistrar,
        ToolRegistryEntry,
        content_subdir,
        serve_readiness,
        serve_routes,
    )
    from agent_connector_sdk.mcp.tool_surface import register_action_tools

    registrar: ServerRegistrar = register_router_tools
    entry: ToolRegistryEntry = ("router", "ROUTERTOOL", registrar)
    probe: ReadinessProbe = _ready
    value: ReadinessValue = 3
    inline: InlineTool = inline_plain
    registration: Registration = lambda context: None  # noqa: E731
    assert READINESS_PATH in RESERVED_PATHS and "/health" in RESERVED_PATHS
    assert (value, inline(), registration) == (3, "plain", registration)
    assert str(content_subdir("assets/content")) == "assets/content"

    mcp: FastMCP[Any] = FastMCP("plain")
    assert register_action_tools(mcp, [entry], prefixes={"demo_router": "x"}) == [
        "router"
    ]
    serve_routes(mcp, (Route("/version", _version),))
    serve_readiness(mcp, probe)
    assert {"x_status", "x_purge"} <= _tools(mcp)
    with TestClient(mcp.http_app()) as client:
        assert client.get("/version").text == "v"
        assert client.get(READINESS_PATH).json()["status"] == "ready"
