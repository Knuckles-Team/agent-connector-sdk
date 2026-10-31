"""Stdio MCP transport helpers for the MCP package connector."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from scion_sdk.config import setting
from scion_sdk.paths import platform_config_file

logger = logging.getLogger(__name__)

#: An injected tool caller: ``(tool_name, arguments) -> decoded result``.
CallToolFn = Callable[[str, dict[str, Any]], Any]


class McpStdioProhibitedError(PermissionError):
    """This process may not spawn stdio MCP children (``MCP_STDIO_PROHIBITED``)."""


def run_sync(coro: Coroutine[Any, Any, Any], *, timeout: float | None = None) -> Any:
    """Run ``coro`` to completion from synchronous code.

    Inside a running event loop, or with a ``timeout``, the coroutine runs on
    a fresh loop in a worker thread. On timeout the caller is released and the
    worker thread is abandoned, not joined.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if timeout is None:
            return asyncio.run(coro)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False)


def load_mcp_servers() -> dict[str, Any]:
    """The ``mcpServers`` map of the configured ``mcp_config.json`` (empty if unreadable)."""
    path = setting("MCP_CONFIG") or platform_config_file("mcp_config.json")
    try:
        servers = json.loads(Path(path).read_text(encoding="utf-8")).get("mcpServers")
    except (OSError, ValueError, AttributeError):
        logger.warning("the configured MCP catalog could not be read")
        return {}
    return servers if isinstance(servers, dict) else {}


def configured_mcp_server(
    servers: dict[str, Any], server_name: str
) -> tuple[str, dict[str, Any]] | None:
    """Select a configured server by name, then ``<name>-mcp``, then the
    ``*-api``/``*-agent`` to ``*-mcp`` deployment alias. Never synthesizes one.
    """
    requested = str(server_name or "").strip()
    if not requested:
        return None
    candidates = [requested, f"{requested}-mcp"]
    for suffix in ("-api", "-agent"):
        if requested.endswith(suffix):
            candidates.append(f"{requested[: -len(suffix)]}-mcp")
            break
    for candidate in dict.fromkeys(candidates):
        config = servers.get(candidate)
        if isinstance(config, dict):
            return candidate, dict(config)
    return None


def _default_call_tool(server_name: str) -> CallToolFn:
    """A stdio tool caller for ``server_name``: one short session per call."""
    if setting("MCP_STDIO_PROHIBITED", default=False):
        raise McpStdioProhibitedError(
            f"stdio MCP server {server_name!r} is prohibited in this process"
        )
    resolved = configured_mcp_server(load_mcp_servers(), server_name)
    if resolved is None or not resolved[1].get("command"):
        raise KeyError(
            f"no MCP server {server_name!r} with a 'command' in mcp_config.json; "
            "pass call_tool=... to use this connector offline"
        )
    config = resolved[1]
    from scion_sdk.ports.session import TransportEndpoint
    from scion_sdk.transports.mcp import McpTransport

    endpoint = TransportEndpoint(
        command=str(config["command"]),
        args=tuple(str(arg) for arg in config.get("args", [])),
        env={
            k: os.path.expandvars(str(v)) for k, v in (config.get("env") or {}).items()
        },
    )

    def _call(tool_name: str, arguments: dict[str, Any]) -> Any:
        async def _run() -> Any:
            async with McpTransport().session(endpoint) as session:
                return await session.call_tool(tool_name, arguments)

        return run_sync(_run())

    return _call
