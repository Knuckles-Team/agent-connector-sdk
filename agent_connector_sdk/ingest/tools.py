"""Ingest tools declared as data and registered by the SDK.

A connector declares each ingest tool as an :class:`IngestTool` (its name, title
and a ``source`` function that reads the provider) and passes
``ingest_registration(stream, tools, get_client)`` in ``Connector(extra_registrations=...)``.
The SDK opens the client, runs the source, maps and commits through the
:class:`~agent_connector_sdk.ingest.stream.SourceStream`, and registers the
tool with the standard annotations and tags. The connector keeps the source and
its mappers.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.ingest.mapping import Mapped
from agent_connector_sdk.ingest.paging import CursorStrategy
from agent_connector_sdk.ingest.stream import SourceStream, open_client

__all__ = ["INGEST_TOOL_TAGS", "IngestTool", "ingest_registration"]

INGEST_TOOL_TAGS = frozenset({"ingest", "mutating"})


@dataclass(frozen=True)
class IngestTool:
    """One ingest tool.

    Attributes:
        name: The MCP tool name.
        title: The tool title shown to clients.
        source: ``source(client, **tool_arguments)``. Returns a :class:`Mapped`,
            or the provider records to map with ``kind``. With ``paged`` it is
            ``source(client, cursor, **tool_arguments)`` and returns the page
            records (or ``(records, next_cursor)`` without a ``strategy``).
        kind: The mapper name in the stream, for sources that return records.
        description: The tool description; the source's docstring when empty.
        paged: Walk the source with :meth:`SourceStream.sync`.
        strategy: The cursor strategy of a paged source.
        idempotent: Whether a repeated call changes nothing more.
    """

    name: str
    title: str
    source: Callable[..., Any]
    kind: str | None = None
    description: str = ""
    paged: bool = False
    strategy: CursorStrategy | None = None
    idempotent: bool = True


def _tool_function(
    stream: SourceStream, spec: IngestTool, get_client: Callable[..., Any]
) -> Callable[..., Any]:
    parameters = list(inspect.signature(spec.source).parameters.values())
    skip = 2 if spec.paged else 1
    own = parameters[skip:]

    async def tool(**arguments: Any) -> dict[str, int]:
        async with open_client(get_client) as client:
            if spec.paged:

                async def fetch(cursor: str | None) -> Any:
                    result = spec.source(client, cursor, **arguments)
                    return await result if inspect.isawaitable(result) else result

                assert spec.kind is not None
                return await stream.sync(spec.kind, fetch, strategy=spec.strategy)
            produced = spec.source(client, **arguments)
            if inspect.isawaitable(produced):
                produced = await produced
            if isinstance(produced, Mapped):
                counts = await stream.mapped(produced)
            else:
                assert spec.kind is not None
                counts = await stream.records(spec.kind, produced)
            return counts or {"nodes": 0, "edges": 0}

    tool.__name__ = spec.name
    tool.__doc__ = spec.description or inspect.getdoc(spec.source) or spec.title
    tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        own, return_annotation=dict[str, int]
    )
    tool.__annotations__ = {p.name: p.annotation for p in own} | {
        "return": dict[str, int]
    }
    return tool


def ingest_registration(
    stream: SourceStream,
    tools: Sequence[IngestTool],
    get_client: Callable[..., Any],
) -> Callable[[Any], None]:
    """A registrar for ``Connector(extra_registrations=(...))`` serving ``tools``."""
    for spec in tools:
        if spec.paged and spec.kind is None:
            raise ValueError(f"paged ingest tool {spec.name!r} needs a kind")

    def register(mcp: Any) -> None:
        for spec in tools:
            mcp.tool(
                name=spec.name,
                annotations={
                    "title": spec.title,
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": spec.idempotent,
                    "openWorldHint": True,
                },
                tags=set(INGEST_TOOL_TAGS),
            )(_tool_function(stream, spec, get_client))

    return register
