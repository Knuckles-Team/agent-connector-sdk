"""MCP package connector: any MCP server's document-yielding tool as a source.

One adapter reaches a connector package through its MCP server, calls a
declared tool and maps the JSON result to :class:`SourceDocument` objects, so
a package becomes a document source by configuration
(:mod:`~agent_connector_sdk.source_connectors.connectors.package_manifest`
holds the presets).

Two ways to supply the transport:

* an injected ``call_tool(tool_name, arguments) -> result`` callable;
* a stdio server read from the platform ``mcp_config.json``
  (``MCP_CONFIG``, else
  :func:`~agent_connector_sdk.paths.platform_config_file`), opened through
  :class:`~agent_connector_sdk.transports.mcp.McpTransport`. The ``mcp``
  extra supplies the client. ``MCP_STDIO_PROHIBITED=true`` refuses stdio.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any

from agent_connector_sdk.config import setting
from agent_connector_sdk.paths import platform_config_file

from ..base import (
    CheckpointedBatch,
    ConnectorCheckpoint,
    LoadConnector,
    PollConnector,
    SourceDocument,
    default_external_access,
)
from ..registry import register_source
from .rest import _dig

__all__ = [
    "CallToolFn",
    "MCPPackageConnector",
    "McpStdioProhibitedError",
    "configured_mcp_server",
    "load_mcp_servers",
    "run_sync",
]

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
    from agent_connector_sdk.ports.session import TransportEndpoint
    from agent_connector_sdk.transports.mcp import McpTransport

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


@register_source("mcp")
class MCPPackageConnector(LoadConnector, PollConnector):
    """Adapt an MCP agent-package's document-yielding tool into a connector.


    Config:
        package: Logical package name (e.g. ``scholarx``); resolves a preset from
            :mod:`package_manifest` for the remaining fields when they are omitted.
        server: MCP server name in ``mcp_config.json`` (defaults to
            ``<package>-mcp``).
        tool: The tool to call (e.g. ``search_papers``).
        args: Static arguments passed to the tool.
        query_arg: Name of the tool argument carrying the search query (optional).
        query: Search query value bound to ``query_arg``.
        records_field: Dotted path to the array of records in the tool result
            (default: the result is itself the list).
        id_field / title_field / text_field / updated_field: record→document map.
        cursor_arg / cursor_field: pagination argument + response cursor field.
        call_tool: Optional injected ``(tool, args) -> result`` for offline use.
    """

    provider = "MCP Agent-Package"

    def configure(
        self,
        *,
        package: str = "",
        server: str = "",
        tool: str = "",
        args: dict[str, Any] | None = None,
        query_arg: str = "",
        query: str = "",
        records_field: str = "",
        id_field: str = "id",
        title_field: str = "title",
        text_field: str = "text",
        updated_field: str = "",
        cursor_arg: str = "",
        cursor_field: str = "",
        doc_type: str = "document",
        call_tool: CallToolFn | None = None,
        **_: object,
    ) -> None:
        # Merge a preset from the parity catalog when only a package is named.
        if package and not tool:
            from .package_manifest import get_preset

            preset = get_preset(package)
            if preset:
                server = server or preset.get("server", "")
                tool = tool or preset.get("tool", "")
                records_field = records_field or preset.get("records_field", "")
                id_field = preset.get("id_field", id_field)
                title_field = preset.get("title_field", title_field)
                text_field = preset.get("text_field", text_field)
                updated_field = updated_field or preset.get("updated_field", "")
                cursor_field = cursor_field or preset.get("cursor_field", "")
                cursor_arg = cursor_arg or preset.get("cursor_arg", "")
                query_arg = query_arg or preset.get("query_arg", "")
                doc_type = preset.get("doc_type", doc_type)
                args = {**preset.get("args", {}), **(args or {})}

        if not tool:
            raise ValueError(
                "MCPPackageConnector requires a 'tool' (or a known 'package' preset)"
            )

        self.package = package
        self.server = server or (f"{package}-mcp" if package else "")
        self.tool = tool
        self.args = dict(args or {})
        self.query_arg = query_arg
        self.query = query
        self.records_field = records_field
        self.id_field = id_field
        self.title_field = title_field
        self.text_field = text_field
        self.updated_field = updated_field
        self.cursor_arg = cursor_arg
        self.cursor_field = cursor_field
        self.doc_type = doc_type
        self._call_tool = call_tool

    @property
    def name(self) -> str:
        return f"mcp:{self.package or self.server or self.tool}"

    def _caller(self) -> CallToolFn:
        if self._call_tool is None:
            self._call_tool = _default_call_tool(self.server)
        return self._call_tool

    def health_check(self) -> bool:
        return bool(self.tool) and (self._call_tool is not None or bool(self.server))

    # -- record → document mapping -----------------------------------------

    def _records(self, result: Any) -> list[dict[str, Any]]:
        data = _dig(result, self.records_field) if self.records_field else result
        if isinstance(data, dict):
            # Some tools wrap the list under a single obvious key.
            for key in ("results", "items", "records", "data", "documents"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    def _to_document(self, record: dict[str, Any]) -> SourceDocument | None:
        rid = _dig(record, self.id_field)
        text = _dig(record, self.text_field)
        if rid is None or not isinstance(text, str) or not text.strip():
            return None
        title = _dig(record, self.title_field)
        updated = _dig(record, self.updated_field) if self.updated_field else None
        return SourceDocument(
            id=str(rid),
            source_uri=f"mcp://{self.package or self.server}/{rid}",
            title=str(title) if title else str(rid),
            text=text,
            doc_type=self.doc_type,
            # Persist only neutral provenance, never the full upstream record;
            # unused fields commonly contain identities, tokens, or private URLs.
            metadata={
                "package": self.package,
                "tool": self.tool,
                "source_system": "mcp",
            },
            # This record shape has no ACL: unknown access is quarantined.
            external_access=default_external_access(),
            updated_at=str(updated) if updated is not None else None,
        )

    def _call(
        self, cursor: str | None = None
    ) -> tuple[list[SourceDocument], str | None]:
        arguments = dict(self.args)
        if self.query_arg and self.query:
            arguments[self.query_arg] = self.query
        if self.cursor_arg and cursor:
            arguments[self.cursor_arg] = cursor
        result = self._caller()(self.tool, arguments)
        records = self._records(result)
        docs = [d for d in (self._to_document(r) for r in records) if d is not None]
        next_cursor = None
        if self.cursor_field:
            top = _dig(result, self.cursor_field) if isinstance(result, dict) else None
            next_cursor = str(top) if top else None
        return docs, next_cursor

    # -- LoadConnector / PollConnector -------------------------------------

    def load(self) -> Iterator[SourceDocument]:
        docs, _ = self._call()
        yield from docs

    def poll(self, checkpoint: ConnectorCheckpoint | None = None) -> CheckpointedBatch:
        """One tool call per poll, carrying a pagination cursor when supported.

        When the tool or preset exposes a cursor, ``poll`` advances
        a page at a time; otherwise it returns a single batch with ``has_more``
        false. ``seen_ids`` dedups across polls for cursor-less sources.
        """
        cursor = checkpoint.cursor if checkpoint else None
        prior_ids = set(checkpoint.seen_ids) if checkpoint else set()
        docs, next_cursor = self._call(cursor)
        fresh = [d for d in docs if d.id not in prior_ids]
        new_ids = prior_ids | {d.id for d in docs}
        cp = ConnectorCheckpoint(
            has_more=bool(next_cursor),
            cursor=next_cursor,
            seen_ids=sorted(new_ids)
            if not next_cursor
            else checkpoint.seen_ids
            if checkpoint
            else [],
        )
        return CheckpointedBatch(documents=fresh, checkpoint=cp)
