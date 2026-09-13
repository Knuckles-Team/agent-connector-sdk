"""Tool modes, verbose tools, auto-wire and the tool surface entry point."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.mcp.tool_mode import (
    GATED_TAG,
    GATED_TOOLS_ATTRIBUTE,
    GRANULAR_TAG,
    VALID_TOOL_MODES,
    gated_tool_names,
    registered_tools,
    tool_mode,
)
from agent_connector_sdk.mcp.tool_surface import CondensedEntry, register_tool_surface
from agent_connector_sdk.mcp.verbose_autowire import (
    autowire_verbose_from_condensed,
    register_action_provider,
)
from agent_connector_sdk.mcp.verbose_naming import (
    derive_domains,
    domain_methods,
    service_tool_prefix,
    verbose_tool_name,
)
from agent_connector_sdk.mcp.verbose_tools import register_verbose_tools


class DemoApiBase:
    def authenticate(self) -> None:
        """Infrastructure, never a tool."""


class DemoApiItems(DemoApiBase):
    def get_item(self, item_id: str) -> dict[str, str]:
        """Fetch one item."""
        return {"id": item_id}

    def delete_item(self, item_id: str) -> str:
        """Delete one item."""
        return item_id


class DemoApiUsers(DemoApiItems):
    def list_users(self) -> list[str]:
        """List users."""
        return ["u1"]


def get_client() -> DemoApiUsers:
    return DemoApiUsers()


def register_items_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def demo_items(
        action: Literal["get_item", "list_users"], params_json: str = "{}"
    ) -> str:
        """Condensed items tool."""
        return action


def register_free_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def demo_free(action: str, params_json: str = "{}") -> str:
        """Free-form action tool."""
        return action


def test_naming_helpers() -> None:
    owners = domain_methods(DemoApiUsers)
    assert set(owners) == {"get_item", "delete_item", "list_users"}
    assert derive_domains(owners) == {
        "get_item": "items",
        "delete_item": "items",
        "list_users": "users",
    }
    assert service_tool_prefix("demo-api") == "demo"
    assert verbose_tool_name("demo_get", "demo") == "demo_get"
    assert verbose_tool_name("get", "demo") == "demo_get"


def test_tool_mode_reads_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TOOL_MODE", "verbose")
    assert tool_mode() == "verbose"
    monkeypatch.setenv("MCP_TOOL_MODE", "surprise")
    assert tool_mode() == "intent"
    assert "intent" in VALID_TOOL_MODES


async def test_register_verbose_tools_typed_and_params_json() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    manifest = [
        {
            "method": "get_item",
            "summary": "Typed get",
            "params": [{"name": "item_id", "type": "string", "required": True}],
        },
        {"method": "not_on_client"},
    ]
    names = register_verbose_tools(
        mcp, DemoApiUsers, get_client, service="demo-api", manifest=manifest
    )
    assert names == ["demo_delete_item", "demo_get_item", "demo_list_users"]
    assert GRANULAR_TAG in registered_tools(mcp)["demo_get_item"].tags
    async with Client(mcp) as client:
        typed = await client.call_tool("demo_get_item", {"item_id": "7"})
        listed = await client.call_tool("demo_list_users", {"params_json": "{}"})
        cancelled = await client.call_tool(
            "demo_delete_item", {"params_json": '{"item_id": "7"}'}
        )
    assert typed.structured_content == {"id": "7"}
    assert [block.text for block in listed.content] == ['["u1"]']
    assert cancelled.structured_content == {
        "cancelled": True,
        "operation": "delete_item",
    }


def test_intent_mode_gates_condensed_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    module = SimpleNamespace(
        register_items_tools=register_items_tools,
        register_tool_surface=register_tool_surface,
    )
    tags = register_tool_surface(
        mcp, service="demo-api", tools_module=module, mode_override="intent"
    )
    assert tags == ["items"]
    assert gated_tool_names(mcp) == {"demo_items"}
    assert getattr(mcp, GATED_TOOLS_ATTRIBUTE) == {"demo_items"}
    assert GATED_TAG in registered_tools(mcp)["demo_items"].tags
    monkeypatch.setenv("ITEMSTOOL", "false")
    other: FastMCP[Any] = FastMCP("demo")
    assert (
        register_tool_surface(
            other, service="demo-api", tools_module=module, mode_override="condensed"
        )
        == []
    )


def test_both_mode_builds_verbose_and_autowired_surface() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    registry: list[CondensedEntry] = [("items", "ITEMSTOOL", register_items_tools)]
    register_tool_surface(
        mcp,
        service="demo-api",
        client_cls=DemoApiUsers,
        get_client=get_client,
        tool_registry=registry,
        registrars=[register_free_tools],
        action_providers={"demo_free": ["ping", "help"]},
        mode_override="both",
    )
    names = set(registered_tools(mcp))
    assert {
        "demo_items",
        "demo_get_item",
        "demo_items__get_item",
        "demo_items__list_users",
    } <= names
    assert "demo_free" not in names  # tool_registry wins over registrars


def test_registrars_and_action_providers() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_tool_surface(
        mcp,
        service="demo-api",
        registrars=[register_free_tools],
        verbose_register=lambda server: register_action_provider(
            server, "demo_free", DemoApiItems
        ),
        mode_override="verbose",
    )
    assert {"demo_free__get_item", "demo_free__delete_item"} <= set(
        registered_tools(mcp)
    )
    assert autowire_verbose_from_condensed(mcp) == []


def test_invalid_surface_declarations() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    with pytest.raises(ValueError):
        register_tool_surface(mcp, service="demo", mode_override="loud")
    with pytest.raises(ValueError):
        register_tool_surface(
            mcp,
            service="demo",
            registrars=[("items", "ITEMSTOOL")],
            mode_override="condensed",
        )
    with pytest.raises(ValueError):
        register_tool_surface(
            mcp, service="demo", registrars=["not callable"], mode_override="condensed"
        )
