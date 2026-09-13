"""An in-memory sink for connector and extension tests.

:class:`InMemorySink` implements :class:`~agent_connector_sdk.ports.sink.Sink`
with the acknowledgement semantics a durable sink must have, so a connector's
tests can exercise extraction and provisioning end to end without an
epistemic-graph instance:

* a batch is accepted only when every record belongs to the batch cursor's
  stream, and the receipt names the batch digest and the committed cursor;
* re-submitting a batch with a known digest accepts nothing new;
* importing a pack with a known digest imports nothing new.
"""

from __future__ import annotations

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)

__all__ = ["InMemorySink"]


class InMemorySink:
    """Keeps committed batches and imported packs in memory, keyed by digest."""

    def __init__(self) -> None:
        self.batches: dict[str, RecordBatch] = {}
        self.packs: dict[str, ContentPack] = {}

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit ``batch`` once; a repeated digest accepts zero records.

        Raises:
            ValueError: a record belongs to a stream other than the cursor's.
        """
        if any(record.stream != batch.cursor.stream for record in batch.records):
            raise ValueError("every record must belong to the batch cursor's stream")
        digest = batch.digest
        accepted = 0 if digest in self.batches else len(batch.records)
        self.batches.setdefault(digest, batch)
        return IngestionReceipt(
            batch_digest=digest, accepted=accepted, committed_cursor=batch.cursor
        )

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import ``pack`` once; a repeated digest imports zero entries."""
        digest = pack.digest
        imported = 0 if digest in self.packs else len(pack.entries)
        self.packs.setdefault(digest, pack)
        return PackImportReceipt(pack_digest=digest, imported=imported)
