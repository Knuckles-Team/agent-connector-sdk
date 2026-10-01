"""One sync pass over a stream using EG's sole durable checkpoint authority."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Self

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceIngestionReceipt,
    SourceIngestionRequest,
)

from agent_connector_sdk.contracts import RecordPage, StreamDescriptor
from agent_connector_sdk.ports.repair_proposals import RepairProposalStore
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.ports.source_adapter import SourceAdapter
from agent_connector_sdk.runner.errors import (
    SchemaDriftQuarantined,
    SinkReceiptError,
    StreamPaused,
)
from agent_connector_sdk.runner.logs import structured
from agent_connector_sdk.schema_drift import (
    DriftClassification,
    EvolutionPolicy,
    SchemaContract,
    classify_schema_drift,
)

__all__ = ["SyncOutcome", "SyncTarget", "commit_page", "sync_stream"]

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncTarget:
    """Where a stream's pages go and how far one pass may read."""

    connector: str
    sink: Sink
    max_pages: int
    empty_authoritative_approval: str | None = None
    schema_contract: SchemaContract | None = None
    evolution_policy: EvolutionPolicy = EvolutionPolicy.REVIEW
    tenant: str | None = None
    repair_proposals: RepairProposalStore | None = None

    @classmethod
    def configured(
        cls,
        connector: str,
        sink: Sink,
        max_pages: int,
        empty_authoritative_approval: str,
    ) -> Self:
        """Build a target from a connector descriptor's normalized values."""
        return cls(
            connector=connector,
            sink=sink,
            max_pages=max_pages,
            empty_authoritative_approval=empty_authoritative_approval or None,
        )


@dataclass(frozen=True)
class SyncOutcome:
    """What one sync pass durably committed."""

    stream: str
    pages: int
    records: int
    accepted: int
    exhausted: bool
    checkpoint: SourceCheckpoint | None


def _empty_approval(page: RecordPage, target: SyncTarget) -> str | None:
    empty_full = page.mode is SourceIngestionMode.FULL and not page.records
    empty_reconcile = (
        page.mode is SourceIngestionMode.RECONCILE
        and not page.records
        and page.authoritative_live_ids == ()
    )
    return (
        target.empty_authoritative_approval if empty_full or empty_reconcile else None
    )


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


async def commit_page(
    page: RecordPage,
    target: SyncTarget,
    *,
    expected_previous_checkpoint: SourceCheckpoint | None,
) -> SourceIngestionReceipt:
    """Commit one exact generated request and verify its terminal receipt."""
    request = _source_request(page, target, expected_previous_checkpoint)
    _check_drift(page, target, request)
    receipt = await target.sink.submit(request)
    if not _receipt_binds_request(request, receipt):
        raise SinkReceiptError("ingestion receipt does not acknowledge the request")
    return receipt


def _check_drift(
    page: RecordPage, target: SyncTarget, request: SourceIngestionRequest
) -> None:
    report = classify_schema_drift(
        target.schema_contract,
        page.schema_contract,
        source=target.connector,
        stream=page.checkpoint.stream,
        tenant=target.tenant,
        observed_sample_digest=request.canonical_digest(),
        policy=target.evolution_policy,
    )
    if report.classification is not DriftClassification.COMPATIBLE:
        _logger.warning(
            "source page quarantined",
            extra=structured(
                "schema_drift_quarantined",
                target.connector,
                report=report.model_dump(mode="json"),
            ),
        )
        raise SchemaDriftQuarantined(report)


def _source_request(
    page: RecordPage,
    target: SyncTarget,
    expected_previous_checkpoint: SourceCheckpoint | None,
) -> SourceIngestionRequest:
    return SourceIngestionRequest(
        connector=target.connector,
        mode=page.mode,
        strict_schema=page.strict_schema,
        records=list(page.records),
        relationships=list(page.relationships),
        provider_checkpoint=page.checkpoint,
        expected_previous_checkpoint=expected_previous_checkpoint,
        authoritative_live_ids=(
            None
            if page.authoritative_live_ids is None
            else list(page.authoritative_live_ids)
        ),
        empty_authoritative_approval=_empty_approval(page, target),
        withdrawals=list(page.withdrawals),
    )


def _receipt_binds_request(
    request: SourceIngestionRequest, receipt: SourceIngestionReceipt
) -> bool:
    return not (
        receipt.batch_digest != request.canonical_digest()
        or receipt.accepted_checkpoint != request.provider_checkpoint
        or receipt.mode != request.mode
    )


async def _accept_page(
    page: RecordPage,
    target: SyncTarget,
    checkpoint: SourceCheckpoint | None,
) -> tuple[SourceCheckpoint, int]:
    if _is_delta_noop(page, checkpoint):
        _check_drift(page, target, _source_request(page, target, checkpoint))
        return page.checkpoint, 0
    receipt = await commit_page(page, target, expected_previous_checkpoint=checkpoint)
    return receipt.accepted_checkpoint, receipt.affected_count


def _discovered_target(target: SyncTarget, descriptor: StreamDescriptor) -> SyncTarget:
    if target.schema_contract is None:
        target = replace(
            target,
            schema_contract=descriptor.schema_contract,
            evolution_policy=descriptor.evolution_policy,
        )
    return target


async def sync_stream(
    session: McpSession, adapter: SourceAdapter, target: SyncTarget
) -> SyncOutcome:
    """Resume from EG status and commit each provider page before extracting next.

    Raises:
        StreamPaused: ``target.repair_proposals`` names an unresolved repair
            proposal for this stream; no page is extracted or submitted.
    """
    descriptor = await adapter.discover(session)
    stream = descriptor.stream
    target = _discovered_target(target, descriptor)
    if target.repair_proposals is not None and await target.repair_proposals.paused(
        target.connector, stream
    ):
        raise StreamPaused(target.connector, stream)
    status = await target.sink.source_status(target.connector, stream)
    checkpoint = status.accepted_checkpoint
    pages = records = accepted = 0
    exhausted = False
    while pages < target.max_pages and not exhausted:
        page = await adapter.extract(session, checkpoint)
        checkpoint, newly_accepted = await _accept_page(page, target, checkpoint)
        exhausted = page.exhausted
        pages, records = pages + 1, records + len(page.records)
        accepted += newly_accepted
    return SyncOutcome(stream, pages, records, accepted, exhausted, checkpoint)
