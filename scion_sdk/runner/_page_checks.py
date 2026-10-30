"""Pure checks over source pages and ingestion receipts."""

from __future__ import annotations

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceIngestionReceipt,
    SourceIngestionRequest,
)

from scion_sdk.contracts import RecordPage


def _is_delta_noop(page: RecordPage, checkpoint: SourceCheckpoint | None) -> bool:
    """Whether a polling response carries neither effects nor checkpoint progress."""
    return (
        checkpoint is not None
        and page.exhausted
        and page.mode is SourceIngestionMode.DELTA
        and page.checkpoint == checkpoint
        and not page.records
        and not page.relationships
        and not page.withdrawals
    )


def _receipt_binds_request(
    request: SourceIngestionRequest, receipt: SourceIngestionReceipt
) -> bool:
    return not (
        receipt.batch_digest != request.canonical_digest()
        or receipt.accepted_checkpoint != request.provider_checkpoint
        or receipt.mode != request.mode
    )
