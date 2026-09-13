"""One sync pass over a stream: extract, commit, checkpoint, page by page."""

from __future__ import annotations

from dataclasses import dataclass

from agent_connector_sdk.contracts import (
    IngestionReceipt,
    RecordBatch,
    RecordPage,
    SyncCursor,
)
from agent_connector_sdk.ports.checkpoint_store import CheckpointStore
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.runner.errors import SinkReceiptError

__all__ = ["SyncOutcome", "SyncTarget", "commit_page", "sync_stream"]


@dataclass(frozen=True)
class SyncTarget:
    """Where a stream's pages go and how far one pass may read."""

    connector: str
    mapping_reference: str
    sink: Sink
    store: CheckpointStore
    max_pages: int


@dataclass(frozen=True)
class SyncOutcome:
    """What one sync pass did."""

    stream: str
    pages: int
    records: int
    accepted: int
    exhausted: bool
    cursor: SyncCursor | None


async def commit_page(page: RecordPage, target: SyncTarget) -> IngestionReceipt:
    """Submit one page and record its cursor only after the sink committed it.

    Raises:
        SinkReceiptError: the receipt does not acknowledge this batch and cursor;
            nothing is recorded.
    """
    batch = RecordBatch(
        connector=target.connector,
        mapping_reference=target.mapping_reference,
        records=page.records,
        cursor=page.cursor,
    )
    receipt = await target.sink.submit(batch)
    if receipt.batch_digest != batch.digest or receipt.committed_cursor != batch.cursor:
        raise SinkReceiptError("ingestion receipt does not acknowledge the batch")
    await target.store.record_ingestion(target.connector, receipt)
    return receipt


async def sync_stream(
    session: McpSession, adapter: SourceAdapter, target: SyncTarget
) -> SyncOutcome:
    """Verify the source, resume from the committed cursor, and drain pages.

    Each page is committed before the next is extracted, and the next page is
    requested from the cursor the sink committed. A pass stops when the
    stream is exhausted or after ``target.max_pages`` pages; the next pass
    resumes from the last committed cursor.
    """
    stream = (await adapter.discover(session)).stream
    cursor = await target.store.committed_cursor(target.connector, stream)
    pages = records = accepted = 0
    exhausted = False
    while pages < target.max_pages and not exhausted:
        page = await adapter.extract(session, cursor)
        receipt = await commit_page(page, target)
        cursor, exhausted = receipt.committed_cursor, page.exhausted
        pages, records = pages + 1, records + len(page.records)
        accepted += receipt.accepted
    return SyncOutcome(stream, pages, records, accepted, exhausted, cursor)
