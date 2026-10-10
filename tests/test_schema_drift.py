"""SI-04/05: normalized drift and quarantine precede every sink effect."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
    SourceRecordProvenance,
)

import agent_connector_sdk
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.manifest.live_contract import validate_live_tool_contract
from agent_connector_sdk.ports.session import McpSession
from agent_connector_sdk.runner.errors import SchemaDriftQuarantined
from agent_connector_sdk.runner.syncing import SyncTarget, commit_page, sync_stream
from agent_connector_sdk.schema_drift import (
    DriftClassification,
    EvolutionPolicy,
    SchemaContract,
    SchemaDriftReport,
    classify_schema_drift,
)
from agent_connector_sdk.testing.results import SessionFactory
from agent_connector_sdk.testing.sinks import InMemorySink

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "state"],
    "properties": {
        "id": {"type": "string"},
        "state": {"type": "string", "enum": ["open", "closed"]},
        "detail": {"type": "object", "properties": {"count": {"type": "integer"}}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


def contract(schema: dict[str, Any]) -> SchemaContract:
    return SchemaContract.from_schema(schema, identifier_fields=("id",))


def classify(
    current: SchemaContract | None, policy: EvolutionPolicy = EvolutionPolicy.REVIEW
) -> SchemaDriftReport:
    return classify_schema_drift(
        contract(SCHEMA),
        current,
        source="synthetic",
        stream="items",
        tenant="test-tenant",
        observed_sample_digest="a" * 64,
        policy=policy,
    )


def changed_schema(change: str) -> dict[str, Any]:
    schema = deepcopy(SCHEMA)
    properties = schema["properties"]
    if change == "required_removal":
        del properties["id"]
    elif change == "identifier_type":
        properties["id"]["type"] = "integer"
    elif change == "enum":
        properties["state"]["enum"].append("unknown")
    elif change == "nested":
        properties["detail"]["properties"]["count"]["type"] = "string"
    elif change == "array":
        properties["tags"]["items"]["type"] = "object"
    elif change == "requiredness":
        schema["required"].append("detail")
    elif change == "unknown":
        properties["id"]["pattern"] = "^x"
    elif change == "optional":
        properties["note"] = {"type": "string"}
    else:
        raise AssertionError(change)
    return schema


def test_normalized_digest_preserves_semantic_property_names() -> None:
    reordered = deepcopy(SCHEMA)
    reordered["required"].reverse()
    reordered["properties"]["state"]["enum"].reverse()
    reordered["description"] = "presentation only"
    assert contract(reordered).digest() == contract(SCHEMA).digest()
    assert (
        classify(contract(reordered)).classification is DriftClassification.COMPATIBLE
    )
    titled = deepcopy(SCHEMA)
    titled["properties"]["title"] = {"type": "string"}
    assert contract(titled).digest() != contract(SCHEMA).digest()


def test_optional_addition_requires_declared_policy() -> None:
    current = contract(changed_schema("optional"))
    assert classify(current).classification is DriftClassification.REQUIRES_REVIEW
    report = classify(current, EvolutionPolicy.OPTIONAL_FIELDS)
    assert report.classification is DriftClassification.COMPATIBLE
    assert report.reason_codes == ("FIELD_ADDED",)


def test_identifier_semantics_and_missing_evidence_fail_closed() -> None:
    changed = SchemaContract.from_schema(SCHEMA, identifier_fields=("state",))
    report = classify(changed)
    assert report.classification is DriftClassification.BREAKING
    assert report.reason_codes == ("IDENTIFIER_CHANGED",)
    assert classify(None).classification is DriftClassification.REQUIRES_REVIEW


class SyntheticAdapter:
    kind = "synthetic"

    def __init__(
        self, current: SchemaContract | None, *, noop: SourceCheckpoint | None = None
    ) -> None:
        self.current = current
        self.noop = noop
        self.seen: list[SourceCheckpoint | None] = []

    def describe(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(kind=self.kind)

    async def discover(self, session: McpSession) -> StreamDescriptor:
        return StreamDescriptor(
            stream="items",
            tool="read",
            schema_sha256=contract(SCHEMA).digest(),
            schema_contract=contract(SCHEMA),
            evolution_policy=EvolutionPolicy.OPTIONAL_FIELDS,
        )

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        self.seen.append(checkpoint)
        return RecordPage(
            records=(
                SourceRecord(
                    stream="items",
                    record_id="item-1",
                    mapping_reference="manifest:synthetic",
                    payload={"id": "item-1", "state": "open", "detail": {"count": 1}},
                    provenance=SourceRecordProvenance(
                        connector="synthetic",
                        adapter_kind="synthetic",
                        server="synthetic",
                        tool="read",
                        tool_schema_sha256=contract(SCHEMA).digest(),
                        source_uri="synthetic://items/item-1",
                    ),
                ),
            ),
            mode=SourceIngestionMode.DELTA,
            strict_schema=False,
            checkpoint=self.noop
            or SourceCheckpoint(stream="items", position={"page": 1}),
            exhausted=True,
            schema_contract=self.current,
        )

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        return ReconciliationReport(
            stream="items", missing_from_source=(), unknown_to_sink=()
        )


@pytest.mark.spec("SDK-SOURCE-INGEST-R002")
async def test_classifier_contract_covers_representative_changes_and_quarantine(
    sessions: SessionFactory,
) -> None:
    """Representative changes classify correctly; a breaking one quarantines."""
    assert classify(contract(SCHEMA)).classification is DriftClassification.COMPATIBLE
    assert (
        classify(contract(changed_schema("unknown"))).classification
        is DriftClassification.REQUIRES_REVIEW
    )
    assert (
        classify(contract(changed_schema("identifier_type"))).classification
        is DriftClassification.BREAKING
    )
    sink = InMemorySink()
    source = SyntheticAdapter(contract(changed_schema("identifier_type")))
    async with sessions() as session:
        with pytest.raises(SchemaDriftQuarantined):
            await sync_stream(
                session, source, SyncTarget("synthetic", sink, 1, tenant="t")
            )
    assert sink.batches == {}
    assert (await sink.source_status("synthetic", "items")).accepted_checkpoint is None


@pytest.mark.spec("SDK-SOURCE-INGEST-R007")
async def test_drift_gate_runs_between_drain_and_apply_with_no_shacl_or_activation(
    sessions: SessionFactory,
) -> None:
    """The gate sits between draining (extract) and applying (sink submit)."""
    sink = InMemorySink()
    source = SyntheticAdapter(contract(changed_schema("enum")))
    async with sessions() as session:
        with pytest.raises(SchemaDriftQuarantined):
            await sync_stream(session, source, SyncTarget("synthetic", sink, 1))
    assert source.seen == [None], "the page was drained (extracted)"
    assert sink.batches == {}, "the page was never applied (submitted)"
    # Scope: the ingest package owns the drift gate. Other packages may name
    # SHACL as a content kind they serve (``mcp/content.py``).
    ingest_root = Path(agent_connector_sdk.__file__).resolve().parent / "ingest"
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in ingest_root.rglob("*.py")
    ).lower()
    assert "shacl" not in source_text
    assert "activate_schema" not in source_text
    assert "candidate_schema" not in source_text


@pytest.mark.parametrize(
    "change",
    [
        "required_removal",
        "identifier_type",
        "enum",
        "nested",
        "array",
        "requiredness",
        "unknown",
    ],
)
async def test_quarantine_has_zero_writes_and_zero_checkpoint_advance(
    change: str, sessions: SessionFactory
) -> None:
    sink = InMemorySink()
    before = await sink.source_status("synthetic", "items")
    source = SyntheticAdapter(contract(changed_schema(change)))
    async with sessions() as session:
        with pytest.raises(SchemaDriftQuarantined) as caught:
            await sync_stream(
                session, source, SyncTarget("synthetic", sink, 3, tenant="test-tenant")
            )
    report = caught.value.report
    assert isinstance(report, SchemaDriftReport)
    assert report.classification in {
        DriftClassification.BREAKING,
        DriftClassification.REQUIRES_REVIEW,
    }
    assert (
        report.tenant == "test-tenant"
        and report.source == "synthetic"
        and report.stream == "items"
    )
    assert (
        len(report.observed_sample_digest) == 64
        and report.affected_fields
        and report.reason_codes
    )
    assert sink.batches == {}
    assert (
        await sink.source_status("synthetic", "items")
    ).accepted_checkpoint == before.accepted_checkpoint
    assert source.seen == [None]


async def test_optional_field_proceeds_only_after_classification(
    sessions: SessionFactory,
) -> None:
    sink = InMemorySink()
    source = SyntheticAdapter(contract(changed_schema("optional")))
    async with sessions() as session:
        outcome = await sync_stream(session, source, SyncTarget("synthetic", sink, 1))
    assert outcome.pages == 1 and len(sink.batches) == 1
    assert (
        outcome.checkpoint
        == (await sink.source_status("synthetic", "items")).accepted_checkpoint
    )


async def test_direct_commit_and_noop_cannot_bypass_quarantine(
    sessions: SessionFactory,
) -> None:
    sink = InMemorySink()
    checkpoint = SourceCheckpoint(stream="items", position={"page": 1})
    source = SyntheticAdapter(contract(changed_schema("enum")), noop=checkpoint)
    target = SyncTarget("synthetic", sink, 1, schema_contract=contract(SCHEMA))
    async with sessions() as session:
        page = await source.extract(session, checkpoint)
        with pytest.raises(SchemaDriftQuarantined):
            await commit_page(page, target, expected_previous_checkpoint=checkpoint)
        # A second attempt has the identical report identity, no local cursor store.
        with pytest.raises(SchemaDriftQuarantined) as repeated:
            await commit_page(page, target, expected_previous_checkpoint=checkpoint)
    assert repeated.value.report.old_schema_digest == contract(SCHEMA).digest()
    assert sink.batches == {}


async def test_missing_page_contract_quarantines(sessions: SessionFactory) -> None:
    sink = InMemorySink()
    async with sessions() as session:
        with pytest.raises(SchemaDriftQuarantined, match="MISSING_SCHEMA"):
            await sync_stream(
                session, SyntheticAdapter(None), SyncTarget("synthetic", sink, 1)
            )
    assert sink.batches == {}


@pytest.mark.parametrize("keyword", ["const", "enum"])
def test_literal_values_preserve_array_order_and_object_keys(keyword: str) -> None:
    before = ["a", "b"] if keyword == "const" else [["a", "b"]]
    after = ["b", "a"] if keyword == "const" else [["b", "a"]]
    prior = SchemaContract.from_schema({keyword: before})
    current = SchemaContract.from_schema({keyword: after})
    assert prior.digest() != current.digest()
    report = classify_schema_drift(
        prior,
        current,
        source="synthetic",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
    )
    assert report.classification is DriftClassification.REQUIRES_REVIEW
    literal_a = {"title": "a"} if keyword == "const" else [{"title": "a"}]
    literal_b = {"title": "b"} if keyword == "const" else [{"title": "b"}]
    assert SchemaContract.from_schema({keyword: literal_a}).digest() != (
        SchemaContract.from_schema({keyword: literal_b}).digest()
    )


def test_live_contract_snapshot_retains_literal_output_semantics() -> None:
    tool = {
        "name": "read",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        "outputSchema": {"type": "array", "const": ["a", "b"]},
    }
    prior = validate_live_tool_contract({"tools": [tool]}, tool_name="read")
    tool["outputSchema"] = {"type": "array", "const": ["b", "a"]}
    current = validate_live_tool_contract({"tools": [tool]}, tool_name="read")
    assert prior.schema_contract.digest() != current.schema_contract.digest()


async def test_empty_polling_page_cannot_bypass_quarantine(
    sessions: SessionFactory,
) -> None:
    class EmptyAdapter(SyntheticAdapter):
        async def extract(
            self, session: McpSession, checkpoint: SourceCheckpoint | None
        ) -> RecordPage:
            page = await super().extract(session, checkpoint)
            return page.model_copy(update={"records": ()})

    sink = InMemorySink()
    checkpoint = SourceCheckpoint(stream="items", position={"page": 1})
    target = SyncTarget("synthetic", sink, 1, schema_contract=contract(SCHEMA))
    async with sessions() as session:
        initial = await SyntheticAdapter(contract(SCHEMA), noop=checkpoint).extract(
            session, None
        )
        await commit_page(initial, target, expected_previous_checkpoint=None)
        before = dict(sink.batches)
        with pytest.raises(SchemaDriftQuarantined):
            await sync_stream(
                session,
                EmptyAdapter(contract(changed_schema("enum")), noop=checkpoint),
                target,
            )
    assert sink.batches == before
    assert (
        await sink.source_status("synthetic", "items")
    ).accepted_checkpoint == checkpoint


def test_unknown_keyword_values_are_not_treated_as_presentation() -> None:
    before = deepcopy(SCHEMA)
    after = deepcopy(SCHEMA)
    before["x-policy"] = {"title": "allow"}
    after["x-policy"] = {"title": "deny"}
    assert contract(before).digest() != contract(after).digest()
    report = classify_schema_drift(
        contract(before),
        contract(after),
        source="synthetic",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
    )
    assert report.classification is DriftClassification.REQUIRES_REVIEW
    assert report.reason_codes == ("UNKNOWN_SCHEMA_CHANGE",)


@pytest.mark.parametrize(
    "prior,current",
    [
        ({"const": True}, {"const": 1}),
        ({"const": False}, {"const": 0}),
        ({"enum": [True]}, {"enum": [1]}),
        ({"const": {"nested": [False]}}, {"const": {"nested": [0]}}),
        ({"enum": [{"nested": [True]}]}, {"enum": [{"nested": [1]}]}),
        ({"x-policy": {"nested": [True]}}, {"x-policy": {"nested": [1]}}),
        ({"x-policy": None}, {}),
        ({"items": None}, {}),
    ],
)
@pytest.mark.parametrize("policy", list(EvolutionPolicy))
@pytest.mark.parametrize("reverse", [False, True])
def test_json_types_and_keyword_presence_require_review(
    prior: dict[str, Any],
    current: dict[str, Any],
    *,
    policy: EvolutionPolicy,
    reverse: bool,
) -> None:
    before, after = (current, prior) if reverse else (prior, current)
    report = classify_schema_drift(
        contract(before),
        contract(after),
        source="synthetic",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
        policy=policy,
    )
    assert report.old_schema_digest != report.new_schema_digest
    assert report.classification is DriftClassification.REQUIRES_REVIEW
    assert report.reason_codes and report.affected_fields


@pytest.mark.parametrize("keyword", ["const", "enum", "x-policy"])
def test_json_numbers_remain_semantically_equivalent(keyword: str) -> None:
    report = classify_schema_drift(
        contract({keyword: [{"value": 1}]}),
        contract({keyword: [{"value": 1.0}]}),
        source="synthetic",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
    )
    assert report.classification is DriftClassification.COMPATIBLE
    assert report.reason_codes == ()


async def test_boolean_to_number_drift_never_submits(sessions: SessionFactory) -> None:
    before = deepcopy(SCHEMA)
    after = deepcopy(SCHEMA)
    before["properties"]["state"]["enum"] = [True]
    after["properties"]["state"]["enum"] = [1]
    sink = InMemorySink()
    target = SyncTarget("synthetic", sink, 1, schema_contract=contract(before))
    async with sessions() as session:
        with pytest.raises(SchemaDriftQuarantined):
            await sync_stream(session, SyntheticAdapter(contract(after)), target)
    assert sink.batches == {}
    assert (await sink.source_status("synthetic", "items")).accepted_checkpoint is None


@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("enum", DriftClassification.COMPATIBLE),
        ("const", DriftClassification.REQUIRES_REVIEW),
    ],
)
def test_numeric_enum_domain_is_unordered_but_const_array_is_ordered(
    keyword: str, expected: DriftClassification
) -> None:
    report = classify_schema_drift(
        contract({keyword: [100000000000000000000, 11]}),
        contract({keyword: [11, 1e20]}),
        source="synthetic",
        stream="items",
        tenant=None,
        observed_sample_digest="a" * 64,
    )
    assert report.classification is expected
