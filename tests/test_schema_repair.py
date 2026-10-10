"""SDK-SOURCE-INGEST-R003: a proposed repair is recorded and pauses its stream.

The SDK's whole job here is recording a proposal and reading a pause: it never
constructs a candidate graph schema, validates instances, performs a shadow
ingest, or activates a repair (:class:`~agent_connector_sdk.ports.
repair_proposals.RepairProposalStore` declares exactly two methods -- there is
no activation call this test, or anything else in the SDK, could make).
"""

from __future__ import annotations

import pytest
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
    SourceRecordProvenance,
)

from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.ports.repair_proposals import RepairProposalStore
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.runner.errors import StreamPaused
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.schema_drift import (
    DriftClassification,
    EvolutionPolicy,
    SchemaContract,
    SchemaDriftReport,
    classify_schema_drift,
)
from agent_connector_sdk.schema_repair import RepairProposal, propose_repair
from agent_connector_sdk.testing.repair_proposals import InMemoryRepairProposalStore
from agent_connector_sdk.testing.results import SessionFactory
from agent_connector_sdk.testing.sinks import InMemorySink

SCHEMA = {
    "type": "object",
    "required": ["id"],
    "properties": {"id": {"type": "string"}},
}


def _contract(schema: dict[str, object]) -> SchemaContract:
    return SchemaContract.from_schema(schema, identifier_fields=("id",))


def _report(classification_input: SchemaContract | None) -> SchemaDriftReport:
    return classify_schema_drift(
        _contract(SCHEMA),
        classification_input,
        source="repairable",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
    )


class _StaticAdapter:
    """Serves one fixed, drift-free page; counts every ``extract`` call."""

    kind = "static"

    def __init__(self) -> None:
        self.extract_calls = 0

    def describe(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(kind=self.kind)

    async def discover(self, session: McpSession) -> StreamDescriptor:
        return StreamDescriptor(
            stream="items",
            tool="read",
            schema_sha256=_contract(SCHEMA).digest(),
            schema_contract=_contract(SCHEMA),
            evolution_policy=EvolutionPolicy.REVIEW,
        )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        self.extract_calls += 1
        return RecordPage(
            records=(
                SourceRecord(
                    stream="items",
                    record_id="item-1",
                    mapping_reference="manifest:repairable",
                    payload={"id": "item-1"},
                    provenance=SourceRecordProvenance(
                        connector="repairable",
                        adapter_kind="static",
                        server="repairable",
                        tool="read",
                        tool_schema_sha256=_contract(SCHEMA).digest(),
                        source_uri="static://items/item-1",
                    ),
                ),
            ),
            mode=SourceIngestionMode.DELTA,
            strict_schema=False,
            checkpoint=SourceCheckpoint(stream="items", position={"page": 1}),
            exhausted=True,
            schema_contract=_contract(SCHEMA),
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        return ReconciliationReport(
            stream="items", missing_from_source=(), unknown_to_sink=()
        )


def test_propose_repair_needs_a_noncompatible_report_and_full_identity() -> None:
    compatible = _report(_contract(SCHEMA))
    assert compatible.classification is DriftClassification.COMPATIBLE
    with pytest.raises(ValueError, match="no repair proposal"):
        propose_repair(compatible, {"id": "identifier"}, proposer="decider")
    drifted = _report(None)
    assert drifted.classification is not DriftClassification.COMPATIBLE
    with pytest.raises(ValueError, match="non-empty"):
        propose_repair(drifted, {}, proposer="decider")
    with pytest.raises(ValueError, match="proposer"):
        propose_repair(drifted, {"id": "identifier"}, proposer=" ")
    proposal = propose_repair(drifted, {"id": "identifier"}, proposer="decider")
    assert isinstance(proposal, RepairProposal)
    assert proposal.report is drifted
    assert proposal.proposer == "decider"
    assert proposal.proposed_mapping == {"id": "identifier"}


@pytest.mark.spec("SDK-SOURCE-INGEST-R003")
async def test_a_recorded_proposal_pauses_the_stream_before_any_extract_or_submit(
    sessions: SessionFactory,
) -> None:
    sink = InMemorySink()
    adapter = _StaticAdapter()
    store = InMemoryRepairProposalStore()
    assert isinstance(store, RepairProposalStore)
    target = SyncTarget("repairable", sink, 3, repair_proposals=store)

    async with sessions() as session:
        outcome = await sync_stream(session, adapter, target)
    assert outcome.pages == 1 and adapter.extract_calls == 1
    settled = await sink.source_status("repairable", "items")

    proposal = propose_repair(_report(None), {"id": "identifier"}, proposer="decider")
    await store.record(proposal)
    assert await store.paused("repairable", "items") is True

    async with sessions() as session:
        with pytest.raises(StreamPaused, match="items"):
            await sync_stream(session, adapter, target)
    assert adapter.extract_calls == 1, "a paused stream is never extracted"
    assert (
        await sink.source_status("repairable", "items")
    ).accepted_checkpoint == settled.accepted_checkpoint

    store.resolve("repairable", "items")
    assert await store.paused("repairable", "items") is False
    async with sessions() as session:
        outcome = await sync_stream(session, adapter, target)
    assert outcome.pages == 1 and adapter.extract_calls == 2
