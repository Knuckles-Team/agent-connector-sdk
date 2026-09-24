"""``run_mcp_server``: every transport runs inside the validated boundary."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.mcp.parser import create_mcp_parser
from agent_connector_sdk.mcp.server import run_mcp_server


class _Server:
    def __init__(self) -> None:
        self.middlewares: list[object] = []
        self.runs: list[dict[str, Any]] = []

    def add_middleware(self, middleware: object) -> None:
        self.middlewares.append(middleware)

    def run(self, **kwargs: Any) -> None:
        self.runs.append(kwargs)


def _run(*argv: str, middlewares: tuple[object, ...] = ()) -> _Server:
    server = _Server()
    args = create_mcp_parser().parse_args(list(argv))
    run_mcp_server(args, cast(FastMCP[Any], server), middlewares)
    return server


def test_stdio_runs_without_a_network_boundary() -> None:
    marker = object()
    server = _run("--transport", "stdio", middlewares=(marker,))
    assert server.middlewares == [marker]
    assert server.runs == [{"transport": "stdio"}]


def test_network_transport_carries_the_validated_boundary() -> None:
    server = _run(
        "--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8123"
    )
    (run,) = server.runs
    assert (run["transport"], run["host"], run["port"]) == (
        "streamable-http",
        "127.0.0.1",
        8123,
    )
    assert run["middleware"] and run["uvicorn_config"]["proxy_headers"] is False


def test_exposed_listener_without_auth_is_refused() -> None:
    with pytest.raises(SystemExit) as refused:
        _run("--transport", "sse", "--host", "0.0.0.0", "--port", "8123")
    assert refused.value.code == 1
