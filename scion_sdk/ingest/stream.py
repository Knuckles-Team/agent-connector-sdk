"""The one ingest entry a connector declares: a binding plus its mappers.

:class:`SourceStream` replaces the per-connector ``kg_ingest.py`` plumbing. It
builds change sets from mapped records, submits them to the process's
:class:`~scion_sdk.ingest.service.KnowledgeIngest`, pages through a
source resuming from the stream's durable cursor, and returns the standard
``{"nodes": n, "edges": n}`` counts.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from ._stream_paging import FetchPage, _StreamPaging

__all__ = ["FetchPage", "SourceStream", "open_client"]


async def _close_client(client: Any) -> None:
    for name in ("aclose", "close"):
        closer = getattr(client, name, None)
        if callable(closer):
            result = closer()
            if inspect.isawaitable(result):
                await result
            return


@asynccontextmanager
async def open_client(get_client: Callable[..., Any]) -> AsyncIterator[Any]:
    """Build a connector client from its ``get_client`` factory and close it after.

    The factory may be sync or async; ``aclose`` or ``close`` is called when
    the client has one.
    """
    client = get_client()
    if inspect.isawaitable(client):
        client = await client
    try:
        yield client
    finally:
        await _close_client(client)


class SourceStream(_StreamPaging):
    """A connector's ingest stream: binding, named mappers, and the submit path.

    Args:
        binding: Where entity change sets land.
        mappers: Record-kind name to :data:`Mapper` (or a sequence of them).
        document_binding: A second binding for documents, when documents live
            in their own stream.
        projection: Applied to every change set inside :meth:`submit`, before the
            commit (for example :meth:`Pseudonymizer.project
            <scion_sdk.ingest.privacy.Pseudonymizer.project>`).
        before_submit: A guard called with the binding and the projected change
            set; it raises :class:`IngestError` to stop the commit.
        max_records: Refuse a change set with more entities and documents.
        batch_size: Commit a :class:`Mapped` result in batches of this many
            records: all entities first, then the relationships.
        best_effort: Never raise. Empty input, records without an id (or a
            document without text), a refused commit and an unavailable engine
            return ``None`` and log at debug level.
    """

    # Behaviour lives in the capability mixins; the class names the public type.
