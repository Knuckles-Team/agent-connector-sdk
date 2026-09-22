"""Fleet registration, visibility, middleware and served content."""

from __future__ import annotations

import asyncio
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

from agent_connector_sdk.mcp.content import (
    MANIFEST_RESOURCE_URI,
    ConnectorContent,
    ContentError,
    ContentRegistration,
    register_connector_content,
)
from agent_connector_sdk.mcp.middleware import (
    build_middleware,
    caller_bucket,
    rate_limit_client_id,
)
from agent_connector_sdk.mcp.registry import (
    DEFAULT_LEASE_TTL_SECONDS,
    MIN_LEASE_TTL_SECONDS,
    EpistemicGraphServerRegistry,
    ServerRegistry,
    ServerRegistryUnavailableError,
    endpoint_reference,
    lease_ttl_seconds,
    maintain_registration,
    registration_lifespan,
)
from agent_connector_sdk.mcp.visibility import VisibilityTransform
from agent_connector_sdk.mcp.visibility_filters import (
    EMPTY_INTERSECTION,
    bounded_filter_values,
    narrow_values,
    request_values,
)
from agent_connector_sdk.mcp.visibility_policy import (
    HEADER_KEYS,
    QUERY_KEYS,
    VisibilityPolicy,
    current_request,
)


class RecordingRegistry:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, str, int]] = []

    async def register(
        self, name: str, url: str, *, resources: Mapping[str, Any] | None, ttl_secs: int
    ) -> bool:
        self.calls.append((name, url, ttl_secs))
        outcome = self.outcomes[min(len(self.calls), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)


@pytest.mark.parametrize(
    "client", [object(), SimpleNamespace(server_registry=SimpleNamespace())]
)
def test_epistemic_graph_registry_requires_register_server(client: object) -> None:
    with pytest.raises(
        ServerRegistryUnavailableError,
        match=r"^this epistemic-graph client does not expose RegisterServer$",
    ):
        EpistemicGraphServerRegistry(client)


def test_epistemic_graph_registry_uses_register_server() -> None:
    recorder = RecordingRegistry([True])
    registry: ServerRegistry = EpistemicGraphServerRegistry(
        SimpleNamespace(server_registry=recorder)
    )
    assert asyncio.run(
        registry.register("demo", "stdio://demo", resources=None, ttl_secs=60)
    )
    assert recorder.calls == [("demo", "stdio://demo", 60)]


def test_epistemic_graph_dependency_declares_first_compatible_floor() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]

    assert "epistemic-graph>=2.27.0,<3" in project["dependencies"]


def test_lease_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MCP_FLEET_REGISTRATION_TTL_SECS", str(MIN_LEASE_TTL_SECONDS - 1)
    )
    assert lease_ttl_seconds() == DEFAULT_LEASE_TTL_SECONDS
    monkeypatch.setenv("MCP_FLEET_REGISTRATION_TTL_SECS", "120")
    assert lease_ttl_seconds() == 120
    assert endpoint_reference("demo", transport="sse", host="h", port=1) == "sse://h:1"
    assert (
        endpoint_reference("demo", transport="stdio", host="h", port=1)
        == "stdio://demo"
    )


async def test_maintain_registration_retries_after_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = RecordingRegistry([RuntimeError("engine down"), False, True])
    task = asyncio.create_task(
        maintain_registration(
            registry, "demo", "stdio://demo", ttl_secs=60, interval_seconds=0.01
        )
    )
    while len(registry.calls) < 3:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "retrying" in caplog.text and "refused" in caplog.text


async def test_registration_lifespan_starts_and_stops() -> None:
    registry = RecordingRegistry([True])
    lifespan = registration_lifespan(
        registry, name="demo", url="stdio://demo", ttl_secs=60
    )
    async with lifespan(None):
        await asyncio.sleep(0.05)
    assert registry.calls[0] == ("demo", "stdio://demo", 60)


def test_filter_values() -> None:
    assert bounded_filter_values(["a,b", "b"]) == ["a", "b"]
    for bad in (["all"], ["bad value"], ["x" * 20_000]):
        with pytest.raises(ValueError):
            bounded_filter_values(bad)
    assert narrow_values((), ["a"]) == ("a",)
    assert narrow_values(("a", "b"), ["b"]) == ("b",)
    assert narrow_values(("a",), ["z"]) == (EMPTY_INTERSECTION,)
    assert request_values(
        SimpleNamespace(getlist=lambda name: ["x,y"] if name == "tools" else []),
        ("tools",),
    ) == ["x", "y"]


def test_visibility_policy() -> None:
    component = SimpleNamespace(name="demo_get", tags={"items"})
    policy = VisibilityPolicy(disabled_tags=("admin",))
    assert policy.permits(component) and policy.visible([component]) == [component]
    assert not policy.permits(SimpleNamespace(name="", tags=set()))
    narrowed = policy.narrowed({"x-mcp-enabled-tools": "other"}, HEADER_KEYS)
    assert narrowed.visible_one(component) is None
    assert policy.narrowed({"q": "semantic"}, QUERY_KEYS).reject_all
    assert VisibilityPolicy(enabled_tags=("items",)).permits(component)
    assert not VisibilityPolicy(enabled_tags=("items",)).permits(
        SimpleNamespace(name="untagged", tags=set())
    )
    assert current_request() is None and policy.for_current_request() is policy


async def test_visibility_transform_filters_served_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_DISABLED_TOOLS", "hidden")
    mcp: FastMCP[Any] = FastMCP("demo")

    @mcp.tool()
    def visible() -> str:
        return "v"

    @mcp.tool()
    def hidden() -> str:
        return "h"

    @mcp.prompt()
    def hidden_prompt() -> str:
        return "p"

    mcp.add_transform(VisibilityTransform(VisibilityPolicy.from_settings()))
    async with Client(mcp) as client:
        assert [tool.name for tool in await client.list_tools()] == ["visible"]
        assert [prompt.name for prompt in await client.list_prompts()] == [
            "hidden_prompt"
        ]
    transform = VisibilityTransform(VisibilityPolicy(disabled_names=("x",)))

    async def lookup(key: str, *, version: Any = None) -> Any:
        return SimpleNamespace(name=key, tags=set())

    assert await transform.get_tool("x", lookup) is None
    assert (await transform.get_prompt("y", lookup)).name == "y"
    assert await transform.get_resource("x", lookup) is None
    assert (await transform.get_resource_template("z", lookup)).name == "z"
    assert await transform.list_resources([SimpleNamespace(uri="x", tags=set())]) == []
    assert await transform.list_resource_templates([]) == []


def test_middleware() -> None:
    middlewares = build_middleware()
    assert isinstance(middlewares[1], RateLimitingMiddleware)
    assert caller_bucket(None, None) == "anonymous"
    assert caller_bucket("svc", {"sub": "u"}).startswith("caller_")
    assert caller_bucket("svc", {}) != caller_bucket("svc", {"tenant_id": "t"})
    assert rate_limit_client_id(None) == "anonymous"


async def test_connector_content_is_served(package_root: Path) -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    registration = register_connector_content(
        mcp,
        ConnectorContent(
            connector="demo-agent",
            package_root=package_root,
            package_version="1.4.0",
            manifest_path=package_root / "connector_manifest.yml",
        ),
    )
    assert registration == ContentRegistration(skills=1, prompts=1, resources=3)
    async with Client(mcp) as client:
        uris = {str(resource.uri) for resource in await client.list_resources()}
        prompt = await client.get_prompt("demo_agent")
    assert {
        MANIFEST_RESOURCE_URI,
        "ontology://demo-agent/demo.ttl",
        "shapes://demo-agent/demo.shapes.ttl",
        "skill://demo-reader/SKILL.md",
    } <= uris
    assert "continuation" in prompt.messages[0].content.text


def test_connector_content_errors(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "broken.json").write_text(
        json.dumps({"description": "no directive"})
    )
    with pytest.raises(ContentError):
        register_connector_content(
            FastMCP("demo"),
            ConnectorContent(
                connector="c", package_root=tmp_path, package_version="1.0.0"
            ),
        )
    (tmp_path / "prompts" / "broken.json").unlink()
    with pytest.raises(ContentError):
        register_connector_content(
            FastMCP("demo"),
            ConnectorContent(
                connector="c",
                package_root=tmp_path,
                package_version="1.0.0",
                manifest_path=tmp_path / "missing.yml",
            ),
        )


@pytest.mark.parametrize("field", ["connector", "package_version"])
def test_connector_content_requires_identity(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValueError, match="connector and package_version"):
        ConnectorContent(
            connector="" if field == "connector" else "demo-agent",
            package_root=tmp_path,
            package_version="" if field == "package_version" else "1.0.0",
        )
