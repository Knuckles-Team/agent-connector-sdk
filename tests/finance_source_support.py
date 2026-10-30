"""Shared helpers for finance source-adapter tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from scion_sdk.ports.session import TransportEndpoint
from scion_sdk.runner.syncing import SyncTarget, sync_stream
from scion_sdk.transports.mcp import McpTransport


def record_server(records, *, name="finance", takes_mode=True, many=False):
    """Serve ``records`` (one record unless ``many``) from a ``read`` tool."""
    server = FastMCP(name, version="1.0.0")
    page = records if many else [records]
    if takes_mode:

        @server.tool()
        def read(mode: str) -> list[dict]:
            return page

    else:

        @server.tool()
        def read() -> list[dict]:
            return page

    return server


@asynccontextmanager
async def served_session(server: FastMCP) -> AsyncIterator:
    """Open an in-process MCP session against ``server``."""
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        yield session


async def sync_page(session, adapter, sink, connector="finance"):
    """Sync one bounded page of ``adapter`` into ``sink``."""
    return await sync_stream(session, adapter, SyncTarget(connector, sink, max_pages=1))
