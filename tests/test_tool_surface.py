"""The condensed, intent-gated tool surface entry point."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.mcp.tool_surface import (
    GATED_TAG,
    GATED_TOOLS_ATTRIBUTE,
    GRANULAR_TAG,
    CondensedEntry,
    gated_tool_names,
    register_tool_surface,
    registered_tools,
)


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


def test_condensed_tools_always_register_gated() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    tags = register_tool_surface(
        mcp,
        service="demo-api",
        registrars=[register_items_tools],
    )
    assert tags == ["items"]
    assert gated_tool_names(mcp) == {"demo_items"}
    assert getattr(mcp, GATED_TOOLS_ATTRIBUTE) == {"demo_items"}
    tool = registered_tools(mcp)["demo_items"]
    assert {GRANULAR_TAG, GATED_TAG, "items"} <= tool.tags


def test_tools_module_auto_discovery_and_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    module = SimpleNamespace(
        register_items_tools=register_items_tools,
        register_tool_surface=register_tool_surface,
    )
    mcp: FastMCP[Any] = FastMCP("demo")
    assert register_tool_surface(mcp, service="demo-api", tools_module=module) == [
        "items"
    ]

    monkeypatch.setenv("ITEMSTOOL", "false")
    other: FastMCP[Any] = FastMCP("demo")
    assert register_tool_surface(other, service="demo-api", tools_module=module) == []


def test_tool_registry_wins_over_registrars() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    registry: list[CondensedEntry] = [("items", "ITEMSTOOL", register_items_tools)]
    register_tool_surface(
        mcp,
        service="demo-api",
        tool_registry=registry,
        registrars=[register_free_tools],
    )
    names = set(registered_tools(mcp))
    assert "demo_items" in names
    assert "demo_free" not in names  # tool_registry wins over registrars


async def test_condensed_tool_is_callable() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_tool_surface(mcp, service="demo-api", registrars=[register_items_tools])
    async with Client(mcp) as client:
        result = await client.call_tool("demo_items", {"action": "get_item"})
    assert result.content[0].text == "get_item"


def test_retired_verbose_parameters_are_accepted_and_ignored() -> None:
    """``client_cls``/``get_client``/etc. built the retired verbose surface.

    They stay in the signature so the fleet's existing call sites (``client_cls=``,
    ``get_client=``, ...) need no edit, but they register nothing.
    """
    mcp: FastMCP[Any] = FastMCP("demo")
    register_tool_surface(
        mcp,
        service="demo-api",
        client_cls=DemoApiUsers,
        get_client=get_client,
        registrars=[register_items_tools],
        manifest=[{"method": "get_item"}],
        tool_prefix="demo",
        verbose_targets=[{"client_cls": DemoApiUsers, "get_client": get_client}],
        verbose_register=lambda server: None,
        action_providers={"demo_items": ["get_item"]},
    )
    names = set(registered_tools(mcp))
    assert names == {"demo_items"}


def test_invalid_surface_declarations() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    with pytest.raises(ValueError):
        register_tool_surface(mcp, service="demo", registrars=[("items", "ITEMSTOOL")])
    with pytest.raises(ValueError):
        register_tool_surface(mcp, service="demo", registrars=["not callable"])
