"""In-memory conformance sink for generated epistemic-graph contracts."""

from __future__ import annotations

from collections.abc import Callable

from epistemic_graph.connector_pack import pack_digest
from epistemic_graph.generated.connector_pack import (
    McpCatalogSnapshotBinding as PackCatalogBinding,
)
from epistemic_graph.generated.connector_pack import (
    PackDispositionCounts,
    PackImportReceipt,
    PackImportResult,
    PackImportResultImported,
    PackImportResultUnchanged,
    PackProjectionStateNone,
)
from epistemic_graph.generated.source_ingestion import (
    RawAdmissionReceipt,
    SourceIngestionDisposition,
    SourceIngestionMode,
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from agent_connector_sdk.artifacts.pack import CapturedConnectorPack
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.testing.readiness import _in_memory_readiness
from agent_connector_sdk.testing.results import ConformanceResult

__all__ = ["InMemorySink", "run_sink_suite"]

SinkFactory = Callable[[], Sink]
_FIXTURE_DIGEST = "0" * 64
_FIXTURE_CATALOG = PackCatalogBinding(
    authorization_scope_digest=_FIXTURE_DIGEST,
    catalog_generation=1,
    child_connection_generation=1,
    configuration_revision=1,
    snapshot_digest=_FIXTURE_DIGEST,
)


def _validate_source_batch(batch: SourceIngestionRequest) -> None:
    previous = batch.expected_previous_checkpoint
    checkpoint = batch.provider_checkpoint
    if previous is not None and previous.stream != checkpoint.stream:
        raise ValueError("expected and candidate checkpoints must name one stream")
    identities: set[tuple[str, str]] = set()
    for record in batch.records:
        identity = (record.stream, record.record_id)
        if record.stream != checkpoint.stream:
            raise ValueError("every record must belong to the checkpoint stream")
        if record.provenance.connector != batch.connector:
            raise ValueError("record provenance must name the batch connector")
        if identity in identities:
            raise ValueError("record identities must be unique within a batch")
        identities.add(identity)


def _ingestion_receipt(
    batch: SourceIngestionRequest,
    *,
    affected: int,
    disposition: SourceIngestionDisposition,
) -> SourceIngestionReceipt:
    admissions = [
        RawAdmissionReceipt(
            deduplicated=disposition is SourceIngestionDisposition.REPLAYED,
            raw_digest=_FIXTURE_DIGEST,
            record_id=record.record_id,
            stream=record.stream,
        )
        for record in batch.records
    ]
    digest = batch.canonical_digest()
    return SourceIngestionReceipt(
        receipt_id=f"source-ingest:{digest}",
        disposition=disposition,
        mode=batch.mode,
        batch_digest=digest,
        mappings=[],
        raw_admissions=admissions,
        relationship_raw_admissions=[],
        tombstones=[],
        relationship_tombstones=[],
        accepted_checkpoint=batch.provider_checkpoint,
        accepted_checkpoint_digest=_FIXTURE_DIGEST,
        content_hash=batch.provider_checkpoint.content_hash,
        live_set_digest=None,
        relationship_live_set_digest=None,
        affected_count=affected,
        relationship_count=len(batch.relationships or []),
        tombstoned_count=0,
        relationship_tombstoned_count=0,
        committed_graph_version=1,
        receipt_digest=_FIXTURE_DIGEST,
    )


async def _check_committed_receipt(
    factory: SinkFactory, batch: SourceIngestionRequest
) -> ConformanceResult:
    receipt = await factory().submit(batch)
    passed = (
        receipt.batch_digest == batch.canonical_digest()
        and receipt.accepted_checkpoint == batch.provider_checkpoint
        and receipt.affected_count == len(batch.records)
    )
    return ConformanceResult(
        "committed-receipt", passed, "" if passed else "receipt does not bind batch"
    )


async def _check_idempotent_submission(
    factory: SinkFactory, batch: SourceIngestionRequest
) -> ConformanceResult:
    sink = factory()
    first = await sink.submit(batch)
    replay = await sink.submit(batch)
    passed = (
        first.batch_digest == replay.batch_digest == batch.canonical_digest()
        and first.accepted_checkpoint
        == replay.accepted_checkpoint
        == batch.provider_checkpoint
        and replay.affected_count == 0
    )
    return ConformanceResult(
        "idempotent-submission",
        passed,
        "" if passed else "replay changed committed result",
    )


async def _check_checkpoint_compare_and_swap(
    factory: SinkFactory, batch: SourceIngestionRequest
) -> ConformanceResult:
    sink = factory()
    await sink.submit(batch)
    advanced = SourceIngestionRequest(
        connector=batch.connector,
        mode=SourceIngestionMode.DELTA,
        strict_schema=batch.strict_schema,
        records=[],
        relationships=[],
        provider_checkpoint=batch.provider_checkpoint.model_copy(
            update={"position": {"page": 2}}
        ),
        expected_previous_checkpoint=batch.provider_checkpoint,
        authoritative_live_ids=None,
        empty_authoritative_approval=None,
        withdrawals=[],
    )
    await sink.submit(advanced)
    stale = advanced.model_copy(
        update={
            "provider_checkpoint": batch.provider_checkpoint.model_copy(
                update={"position": {"page": 3}}
            )
        }
    )
    try:
        await sink.submit(stale)
    except ValueError:
        return ConformanceResult("checkpoint-compare-and-swap", True)
    return ConformanceResult(
        "checkpoint-compare-and-swap", False, "stale checkpoint was accepted"
    )


async def run_sink_suite(
    factory: SinkFactory, batch: SourceIngestionRequest
) -> list[ConformanceResult]:
    return [
        await _check_committed_receipt(factory, batch),
        await _check_idempotent_submission(factory, batch),
        await _check_checkpoint_compare_and_swap(factory, batch),
    ]


class InMemorySink:
    """Keep committed batches and imported packs in memory by canonical digest."""

    readiness = _in_memory_readiness

    def __init__(self) -> None:
        self.batches: dict[str, SourceIngestionRequest] = {}
        self.packs: dict[str, CapturedConnectorPack] = {}
        self.statuses: dict[tuple[str, str], SourceIngestStatus] = {}

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        return self.statuses.get(
            (connector, stream),
            SourceIngestStatus(
                connector=connector,
                stream=stream,
                accepted_checkpoint=None,
                accepted_checkpoint_digest=None,
                content_hash=None,
                live_set_digest=None,
                relationship_live_set_digest=None,
                last_batch_digest=None,
                last_receipt_id=None,
                committed_graph_version=None,
            ),
        )

    async def submit(self, batch: SourceIngestionRequest) -> SourceIngestionReceipt:
        batch = SourceIngestionRequest.model_validate(batch.model_dump(mode="python"))
        _validate_source_batch(batch)
        digest = batch.canonical_digest()
        if digest in self.batches:
            return _ingestion_receipt(
                self.batches[digest],
                affected=0,
                disposition=SourceIngestionDisposition.REPLAYED,
            )
        status_key = (batch.connector, batch.provider_checkpoint.stream)
        current = await self.source_status(*status_key)
        if current.accepted_checkpoint != batch.expected_previous_checkpoint:
            raise ValueError("expected previous checkpoint is stale")
        self.batches[digest] = batch
        receipt = _ingestion_receipt(
            batch,
            affected=len(batch.records),
            disposition=SourceIngestionDisposition.COMMITTED,
        )
        self.statuses[status_key] = SourceIngestStatus(
            connector=batch.connector,
            stream=batch.provider_checkpoint.stream,
            accepted_checkpoint=batch.provider_checkpoint,
            accepted_checkpoint_digest=receipt.accepted_checkpoint_digest,
            content_hash=batch.provider_checkpoint.content_hash,
            live_set_digest=receipt.live_set_digest,
            relationship_live_set_digest=receipt.relationship_live_set_digest,
            last_batch_digest=receipt.batch_digest,
            last_receipt_id=receipt.receipt_id,
            committed_graph_version=receipt.committed_graph_version,
        )
        return receipt

    async def import_pack(self, pack: CapturedConnectorPack) -> PackImportResult:
        digest = pack_digest(
            pack.connector, _FIXTURE_CATALOG, pack.archive.server, pack.archive.entries
        )
        if digest in self.packs:
            return PackImportResultUnchanged(
                result="unchanged", pack_digest=digest, binding_revision=1
            )
        self.packs[digest] = pack
        return PackImportResultImported(
            result="imported",
            receipt=PackImportReceipt(
                batch_id=f"pack:{digest}",
                binding_revision=1,
                catalog=_FIXTURE_CATALOG,
                committed_version=1,
                connector=pack.connector,
                counts=PackDispositionCounts(
                    published=len(pack.archive.entries) + 1,
                    republished=0,
                    revised=0,
                    unchanged=0,
                    withdrawn=0,
                ),
                pack_digest=digest,
                projection=PackProjectionStateNone(projection="none"),
                record_id=f"pack:{digest}",
                schema_version=1,
                tenant_id="test",
                warnings=[],
            ),
        )
