"""The epistemic-graph sink: a declared contract seam, not an implementation.

epistemic-graph does not yet publish the pack-import or record-ingestion wire
methods (RF-ADR-009 wave W1). Rather than invent them, both operations raise
:class:`NotImplementedError` with a message naming the wave that delivers them.
This module is the only place in the SDK allowed to do so, and the stub gate
(``scripts/check_no_stub.py``) accepts exactly these two messages here.
Nothing that calls this sink counts as done until W1 lands.
"""

from __future__ import annotations

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)

__all__ = [
    "PACK_IMPORT_UNAVAILABLE",
    "RECORD_INGESTION_UNAVAILABLE",
    "EpistemicGraphSink",
]

PACK_IMPORT_UNAVAILABLE = "EG pack import lands in RF-ADR-009 W1"
RECORD_INGESTION_UNAVAILABLE = "EG record ingestion lands in RF-ADR-009 W1"


class EpistemicGraphSink:
    """Submits batches and packs to epistemic-graph through its Python client."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        """Commit a record batch through ``IngestionAuthorityV1`` (W1)."""
        raise NotImplementedError(RECORD_INGESTION_UNAVAILABLE)

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        """Import a content pack keyed by its digest (W1)."""
        raise NotImplementedError(PACK_IMPORT_UNAVAILABLE)
