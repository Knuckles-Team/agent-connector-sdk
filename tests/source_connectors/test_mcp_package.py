"""MCP package source: a tool's records become documents, by preset or explicit map."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scion_sdk.source_connectors import ConnectorCheckpoint, build_connector
from scion_sdk.source_connectors.connectors import mcp_package
from scion_sdk.source_connectors.connectors.mcp_package import (
    CallToolFn,
    MCPPackageConnector,
)
from scion_sdk.source_connectors.connectors.package_manifest import get_preset


def _caller(*pages: Any) -> tuple[list[tuple[str, dict[str, Any]]], CallToolFn]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(tool: str, arguments: dict[str, Any]) -> Any:
        calls.append((tool, arguments))
        return pages[min(len(calls), len(pages)) - 1]

    return calls, call_tool


@pytest.mark.spec("SCION-SOURCE-INGEST-R902.1")
def test_explicit_mapping_yields_documents_with_neutral_metadata() -> None:
    calls, call_tool = _caller(
        {
            "results": [
                {"id": 1, "title": "A", "text": "alpha", "secret": "x"},
                {"id": 2, "text": ""},
            ]
        }
    )
    source = build_connector(
        "mcp",
        {
            "server": "docs-mcp",
            "tool": "search",
            "query_arg": "q",
            "query": "alpha",
            "call_tool": call_tool,
        },
    )
    assert isinstance(source, MCPPackageConnector) and source.health_check()
    (doc,) = source.load()
    assert (doc.id, doc.title, doc.text) == ("1", "A", "alpha")
    assert "secret" not in json.dumps(doc.metadata)
    assert doc.external_access.is_public is False
    assert calls == [("search", {"q": "alpha"})]


def test_package_preset_fills_the_tool_contract() -> None:
    preset = get_preset("scholarx")
    _, call_tool = _caller([])
    source = build_connector("mcp", {"package": "scholarx", "call_tool": call_tool})
    assert source.tool == preset["tool"] and source.name == "mcp:scholarx"


# spec: SCION-SOURCE-INGEST-R902.2
def test_cursor_poll_pages_then_dedups() -> None:
    calls, call_tool = _caller(
        {"items": [{"id": "a", "text": "one"}], "next": "c2"},
        {
            "items": [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}],
            "next": None,
        },
    )
    source = build_connector(
        "mcp",
        {
            "server": "s",
            "tool": "list",
            "cursor_arg": "cursor",
            "cursor_field": "next",
            "call_tool": call_tool,
        },
    )
    first = source.poll()
    assert [d.id for d in first.documents] == ["a"] and first.checkpoint.cursor == "c2"
    second = source.poll(first.checkpoint)
    assert calls[1] == ("list", {"cursor": "c2"})
    assert [d.id for d in second.documents] == ["a", "b"]
    third = source.poll(ConnectorCheckpoint(seen_ids=["a", "b"]))
    assert third.documents == []


def test_tool_is_required() -> None:
    with pytest.raises(ValueError, match="tool"):
        build_connector("mcp", {"server": "s"})


@pytest.mark.parametrize(
    ("requested", "configured"),
    [
        ("scholarx", "scholarx"),
        ("scholarx", "scholarx-mcp"),
        ("servicenow-api", "servicenow-mcp"),
        ("github-agent", "github-mcp"),
    ],
)
@pytest.mark.spec("SCION-SOURCE-INGEST-R902.5")
def test_server_resolution_uses_declared_names_only(
    requested: str, configured: str
) -> None:
    servers = {configured: {"command": "run"}}
    assert mcp_package.configured_mcp_server(servers, requested) == (
        configured,
        {"command": "run"},
    )
    assert mcp_package.configured_mcp_server({}, requested) is None


@pytest.mark.spec("SCION-SOURCE-INGEST-R902.4")
def test_stdio_is_refused_when_prohibited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_STDIO_PROHIBITED", "true")
    source = build_connector("mcp", {"server": "s", "tool": "t"})
    with pytest.raises(mcp_package.McpStdioProhibitedError):
        list(source.load())


def test_unconfigured_server_names_the_offline_option(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    config = tmp_path / "mcp_config.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    monkeypatch.setenv("MCP_CONFIG", str(config))
    monkeypatch.delenv("MCP_STDIO_PROHIBITED", raising=False)
    assert mcp_package.load_mcp_servers() == {"other": {"command": "x"}}
    with pytest.raises(KeyError, match="call_tool"):
        list(build_connector("mcp", {"server": "s", "tool": "t"}).load())


@pytest.mark.spec("SCION-SOURCE-INGEST-R902.3")
def test_mcp_catalog_falls_back_to_the_platform_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    config = tmp_path / "mcp_config.json"
    config.write_text(json.dumps({"mcpServers": {"docs": {"command": "run"}}}))
    seen: list[str] = []

    def platform_config_file(name: str):
        seen.append(name)
        return config

    monkeypatch.delenv("MCP_CONFIG", raising=False)
    monkeypatch.setattr(mcp_package, "platform_config_file", platform_config_file)
    assert mcp_package.load_mcp_servers() == {"docs": {"command": "run"}}
    assert seen == ["mcp_config.json"]


# spec: SCION-SOURCE-INGEST-R902.6
async def test_run_sync_works_inside_a_running_loop() -> None:
    async def answer() -> int:
        return 42

    assert mcp_package.run_sync(answer()) == 42
