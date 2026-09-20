"""An in-memory sink for connector and extension tests.

:class:`InMemorySink` implements :class:`~agent_connector_sdk.ports.sink.Sink`
with the acknowledgement semantics a durable sink must have, so a connector's
tests can exercise extraction and provisioning end to end without an
epistemic-graph instance:

* a batch is accepted only after ``RecordBatch`` has bound every record to one
  connector and cursor stream, and the receipt names the batch digest and the
  committed cursor;
* re-submitting a batch with a known digest accepts nothing new;
* importing a pack with a known digest imports nothing new.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
    SyncCursor,
)
from agent_connector_sdk.ports.sink import Sink, SinkReadiness
from agent_connector_sdk.testing.results import ConformanceResult

__all__ = [
    "InMemorySink",
    "run_sink_suite",
]

SinkFactory = Callable[[], Sink]


async def _check_committed_receipt(
    factory: SinkFactory, batch: RecordBatch
) -> ConformanceResult:
    """A fresh sink binds its acknowledgement to content and cursor."""
    receipt = await factory().submit(batch)
    passed = (
        receipt.batch_digest == batch.digest
        and receipt.committed_cursor == batch.cursor
        and receipt.accepted == len(batch.records)
    )
    detail = "" if passed else "receipt does not bind the submitted batch"
    return ConformanceResult("committed-receipt", passed, detail)


async def _check_idempotent_submission(
    factory: SinkFactory, batch: RecordBatch
) -> ConformanceResult:
    """Replaying one digest preserves its cursor and applies no records twice."""
    sink = factory()
    first = await sink.submit(batch)
    replay = await sink.submit(batch)
    passed = (
        first.batch_digest == replay.batch_digest == batch.digest
        and first.committed_cursor == replay.committed_cursor == batch.cursor
        and replay.accepted == 0
    )
    detail = "" if passed else "same-digest replay changed the committed result"
    return ConformanceResult("idempotent-submission", passed, detail)


async def _check_cursor_compare_and_swap(
    factory: SinkFactory, batch: RecordBatch
) -> ConformanceResult:
    """A stale expected cursor cannot advance the committed source position."""
    sink = factory()
    await sink.submit(batch)
    advanced = RecordBatch(
        connector=batch.connector,
        mapping_reference=batch.mapping_reference,
        records=(),
        expected_previous_cursor=batch.cursor,
        cursor=batch.cursor.model_copy(update={"position": {"page": 2}}),
    )
    await sink.submit(advanced)
    stale = advanced.model_copy(
        update={
            "expected_previous_cursor": batch.cursor,
            "cursor": batch.cursor.model_copy(update={"position": {"page": 3}}),
        }
    )
    try:
        await sink.submit(stale)
    except ValueError:
        return ConformanceResult("cursor-compare-and-swap", True)
    return ConformanceResult(
        "cursor-compare-and-swap", False, "stale expected cursor was accepted"
    )


async def run_sink_suite(
    factory: SinkFactory, batch: RecordBatch
) -> list[ConformanceResult]:
    """Run durable-sink checks with an initial (no previous cursor) batch."""
    return [
        await _check_committed_receipt(factory, batch),
        await _check_idempotent_submission(factory, batch),
        await _check_cursor_compare_and_swap(factory, batch),
    ]


class InMemorySink:
    """Keeps committed batches and imported packs in memory, keyed by digest."""

    def __init__(self) -> None:
        self.batches: dict[str, RecordBatch] = {}
        self.packs: dict[str, ContentPack] = {}
        self.cursors: dict[tuple[str, str], SyncCursor] = {}

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit ``batch`` once; a repeated digest accepts zero records.

        Validation is repeated at this trust boundary because Pydantic's
        ``model_copy(update=...)`` deliberately does not validate updates.
        """
        batch = RecordBatch.model_validate(batch.model_dump(mode="python"))
        digest = batch.digest
        if digest in self.batches:
            return IngestionReceipt(
                batch_digest=digest,
                accepted=0,
                committed_cursor=self.batches[digest].cursor,
            )
        cursor_key = (batch.connector, batch.cursor.stream)
        if self.cursors.get(cursor_key) != batch.expected_previous_cursor:
            raise ValueError("expected previous cursor is stale")
        accepted = len(batch.records)
        self.batches[digest] = batch
        self.cursors[cursor_key] = batch.cursor
        return IngestionReceipt(
            batch_digest=digest, accepted=accepted, committed_cursor=batch.cursor
        )

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import ``pack`` once; a repeated digest imports zero entries."""
        digest = pack.digest
        imported = 0 if digest in self.packs else len(pack.entries)
        self.packs.setdefault(digest, pack)
        return PackImportReceipt(pack_digest=digest, imported=imported)

    async def readiness(self) -> SinkReadiness:
        """Always ready: everything it needs is the in-memory dict above."""
        return SinkReadiness(ready=True)
