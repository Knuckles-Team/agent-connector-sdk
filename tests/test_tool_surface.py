"""The condensed, intent-gated tool surface entry point."""

from __future__ import annotations

import ast
from pathlib import Path
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
from tests.demo_api_fixture import DemoApiUsers, get_client


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


def test_verbose_register_runs_alongside_condensed() -> None:
    """SDK-CONNECTOR-CONTROL-R032: an opt-in verbose registrar runs too."""
    mcp: FastMCP[Any] = FastMCP("demo")

    def register_verbose(server: FastMCP[Any]) -> None:
        @server.tool()
        def demo_get_item(params_json: str = "{}") -> str:
            """Verbose per-method tool."""
            return params_json

    tags = register_tool_surface(
        mcp,
        service="demo-api",
        registrars=[register_items_tools],
        verbose_register=register_verbose,
    )
    assert tags == ["items"]
    names = set(registered_tools(mcp))
    assert names == {"demo_items", "demo_get_item"}
    assert gated_tool_names(mcp) == {"demo_items"}


def test_verbose_register_name_collision_with_condensed_rejected() -> None:
    """A verbose tool reusing a condensed tool's name is refused."""
    mcp: FastMCP[Any] = FastMCP("demo")

    def register_colliding(server: FastMCP[Any]) -> None:
        @server.tool(name="demo_items")
        def demo_items_again(params_json: str = "{}") -> str:
            """Collides with the condensed tool name."""
            return params_json

    with pytest.raises(ValueError, match="collides"):
        register_tool_surface(
            mcp,
            service="demo-api",
            registrars=[register_items_tools],
            verbose_register=register_colliding,
        )


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020")
def test_one_condensed_intent_contract_no_mode_parameter_or_toggle() -> None:
    """``register_tool_surface`` always registers condensed, gated tools.

    There is no ``MCP_TOOL_MODE``/mode parameter or branch; a repository-wide
    scan confirms no live reference to a mode toggle or a separate verbose
    1:1 tool-surface module remains outside explanatory retirement notes.
    """
    import inspect

    mcp: FastMCP[Any] = FastMCP("demo")
    tags = register_tool_surface(
        mcp, service="demo-api", registrars=[register_items_tools]
    )
    assert tags == ["items"]
    assert gated_tool_names(mcp) == {"demo_items"}
    assert "mode" not in inspect.signature(register_tool_surface).parameters

    root = Path(__file__).resolve().parents[1] / "agent_connector_sdk"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            # Prose may name the retired toggle; code must not read or define it.
            if isinstance(node, ast.Name):
                assert "MCP_TOOL_MODE" not in node.id, f"{path}:{node.lineno}"
                assert "tool_mode" not in node.id.lower() or "retired" in text.lower()
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                assert "MCP_TOOL_MODE" not in node.value, f"{path}:{node.lineno}"
