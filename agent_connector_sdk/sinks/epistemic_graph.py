"""The epistemic-graph sink: a declared contract seam, not an implementation.

epistemic-graph does not yet publish the pack-import or generic record-ingestion
wire methods (RF-ADR-009 wave W1). ``SqlSourceBatch`` is an append into an
already-authorized SQL table and its mapping descriptor is inert provenance;
``ApplyChangeEnvelope(s)`` accepts already-mapped graph mutations. Neither is
the accepted ``IngestionAuthorityV1`` boundary that stores raw records, applies
the manifest mapping, and atomically commits its cursor, provenance and receipt.
Rather than invent a third contract or misuse either native method, both
operations raise :class:`NotImplementedError` with a message naming the wave
that delivers them.
This module is the only place in the SDK allowed to do so, and the stub gate
(the shared ``no-stub`` and ``stubs`` hooks) accepts exactly these two messages here.
Nothing that calls this sink counts as done until W1 lands.
"""

from __future__ import annotations

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)
from agent_connector_sdk.ports.sink import SinkReadiness

__all__ = [
    "NOT_READY_REASON",
    "PACK_IMPORT_UNAVAILABLE",
    "RECORD_INGESTION_UNAVAILABLE",
    "EpistemicGraphSink",
]

PACK_IMPORT_UNAVAILABLE = "EG pack import lands in RF-ADR-009 W1"
RECORD_INGESTION_UNAVAILABLE = "EG record ingestion lands in RF-ADR-009 W1"
NOT_READY_REASON = "epistemic-graph native import is not implemented (RF-ADR-009 W1)"


class EpistemicGraphSink:
    """Submits batches and packs to epistemic-graph through its Python client."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Await EG's generated ``IngestionAuthorityV1`` record-batch call."""
        del batch
        raise NotImplementedError(RECORD_INGESTION_UNAVAILABLE)

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import a content pack keyed by its digest (W1)."""
        raise NotImplementedError(PACK_IMPORT_UNAVAILABLE)

    async def readiness(self) -> SinkReadiness:
        """Never ready: the wire methods above are the declared W1 stub."""
        return SinkReadiness(ready=False, reason=NOT_READY_REASON)
