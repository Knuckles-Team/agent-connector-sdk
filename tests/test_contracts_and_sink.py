"""The epistemic-graph seam types and the declared W1 sink stub."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_connector_sdk.contracts import (
    SEAM_SCHEMA_VERSION,
    ArtifactEntry,
    CapabilityDescriptor,
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    PackRecord,
    ReconciliationReport,
    RecordBatch,
    RecordPage,
    RecordProvenance,
    ServerIdentity,
    SourceRecord,
    StreamDescriptor,
    SyncCursor,
    canonical_digest,
)
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.sinks.epistemic_graph import (
    PACK_IMPORT_UNAVAILABLE,
    RECORD_INGESTION_UNAVAILABLE,
    EpistemicGraphSink,
)
from agent_connector_sdk.testing.results import assert_conformant
from agent_connector_sdk.testing.sinks import InMemorySink, run_sink_suite

SERVER = ServerIdentity(name="demo-mcp", version="1.0.0")


def _provenance(tool: str = "reader") -> RecordProvenance:
    return RecordProvenance(
        connector="demo-agent",
        adapter_kind="mcp_tool",
        server="demo-mcp",
        tool=tool,
        tool_schema_sha256="abc",
        source_uri="mcp-tool://demo-mcp/reader/1",
    )


def _record(**payload: object) -> SourceRecord:
    return SourceRecord(
        stream="demo", record_id="1", payload=dict(payload), provenance=_provenance()
    )


def test_canonical_digest_is_deterministic_and_domain_separated() -> None:
    assert canonical_digest("a", {"x": 1, "y": 2}) == canonical_digest(
        "a", {"y": 2, "x": 1}
    )
    assert canonical_digest("a", {"x": 1}) != canonical_digest("b", {"x": 1})
    assert canonical_digest("a", {}).startswith("sha256:")


def test_record_digest_covers_payload_not_provenance() -> None:
    first = _record(title="t")
    moved = first.model_copy(update={"provenance": _provenance(tool="other")})
    assert first.content_digest == moved.content_digest
    assert first.content_digest != _record(title="changed").content_digest


def test_provenance_fields_are_required() -> None:
    with pytest.raises(ValidationError):
        RecordProvenance(
            connector="",
            adapter_kind="mcp_tool",
            server="s",
            tool="t",
            tool_schema_sha256="x",
            source_uri="u",
        )


def test_batch_digest_changes_with_cursor() -> None:
    record = _record(title="t")
    batch = RecordBatch(
        connector="demo-agent",
        mapping_reference="manifest:demo",
        records=(record,),
        cursor=SyncCursor(stream="demo"),
    )
    advanced = batch.model_copy(
        update={"cursor": SyncCursor(stream="demo", watermark="w")}
    )
    assert batch.digest != advanced.digest
    receipt = IngestionReceipt(
        batch_digest=batch.digest, accepted=1, committed_cursor=batch.cursor
    )
    assert receipt.accepted == 1
    with pytest.raises(ValidationError):
        IngestionReceipt(batch_digest="d", accepted=-1, committed_cursor=batch.cursor)
    page = RecordPage(records=(record,), cursor=batch.cursor, exhausted=True)
    assert page.exhausted


def test_batch_digest_binds_expected_previous_cursor() -> None:
    current = SyncCursor(stream="demo", position={"page": 2})
    batch = RecordBatch(
        connector="demo-agent",
        mapping_reference="manifest:demo#schema_mappings/Document",
        records=(_record(title="t"),),
        expected_previous_cursor=SyncCursor(stream="demo", position={"page": 1}),
        cursor=current,
    )
    initial = batch.model_copy(update={"expected_previous_cursor": None})
    assert batch.digest != initial.digest
    with pytest.raises(ValidationError, match="one stream"):
        RecordBatch(
            connector=batch.connector,
            mapping_reference=batch.mapping_reference,
            records=batch.records,
            expected_previous_cursor=SyncCursor(stream="other"),
            cursor=current,
        )


def test_batch_digest_binds_raw_provenance() -> None:
    record = _record(title="t")
    moved = record.model_copy(update={"provenance": _provenance(tool="other")})
    first = RecordBatch(
        connector="demo-agent",
        mapping_reference="manifest:demo",
        records=(record,),
        cursor=SyncCursor(stream="demo"),
    )
    second = first.model_copy(update={"records": (moved,)})
    assert first.digest != second.digest


@pytest.mark.parametrize(
    ("records", "cursor", "message"),
    [
        (
            (_record(title="one"), _record(title="two")),
            SyncCursor(stream="demo"),
            "record identities must be unique",
        ),
        (
            (_record(title="one").model_copy(update={"stream": "other"}),),
            SyncCursor(stream="demo"),
            "cursor stream",
        ),
        (
            (
                _record(title="one").model_copy(
                    update={
                        "provenance": _provenance().model_copy(
                            update={"connector": "other-agent"}
                        )
                    }
                ),
            ),
            SyncCursor(stream="demo"),
            "batch connector",
        ),
    ],
)
def test_record_batch_refuses_ambiguous_commit_scope(
    records: tuple[SourceRecord, ...], cursor: SyncCursor, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        RecordBatch(
            connector="demo-agent",
            mapping_reference="manifest:demo",
            records=records,
            cursor=cursor,
        )


def test_pack_digest_is_order_independent() -> None:
    entries = tuple(
        ArtifactEntry(
            kind="tool",
            uri=f"tool://demo-mcp/{n}",
            name=n,
            media_type="application/json",
            body="{}",
            server=SERVER,
        )
        for n in ("a", "b")
    )
    forward = ContentPack(connector="demo-agent", server=SERVER, entries=entries)
    backward = ContentPack(connector="demo-agent", server=SERVER, entries=entries[::-1])
    assert forward.digest == backward.digest
    record = PackRecord(
        record_kind="Tool", uri=entries[0].uri, name="a", entry_digest=entries[0].digest
    )
    assert record.entry_digest.startswith("sha256:")
    assert PackImportReceipt(pack_digest=forward.digest, imported=2).imported == 2


def test_small_descriptors() -> None:
    assert CapabilityDescriptor(kind="k").schema_version == SEAM_SCHEMA_VERSION
    assert StreamDescriptor(stream="s", tool="t", schema_sha256="x").tool == "t"
    report = ReconciliationReport(
        stream="s", missing_from_source=("1",), unknown_to_sink=()
    )
    assert report.missing_from_source == ("1",)
    with pytest.raises(ValidationError):
        SyncCursor(stream="")


async def test_epistemic_graph_sink_is_a_declared_w1_stub() -> None:
    sink = EpistemicGraphSink(client=object())
    assert isinstance(sink, Sink)
    batch = RecordBatch(
        connector="c", mapping_reference="m", records=(), cursor=SyncCursor(stream="s")
    )
    with pytest.raises(NotImplementedError, match=RECORD_INGESTION_UNAVAILABLE):
        await sink.submit(batch)
    with pytest.raises(NotImplementedError, match=PACK_IMPORT_UNAVAILABLE):
        await sink.import_pack(ContentPack(connector="c", server=SERVER, entries=()))


async def test_in_memory_sink_acknowledges_once() -> None:
    sink = InMemorySink()
    assert isinstance(sink, Sink)
    batch = RecordBatch(
        connector="demo-agent",
        mapping_reference="manifest:demo",
        records=(_record(title="t"),),
        cursor=SyncCursor(stream="demo", watermark="w"),
    )
    first = await sink.submit(batch)
    assert (first.accepted, first.batch_digest, first.committed_cursor) == (
        1,
        batch.digest,
        batch.cursor,
    )
    assert (await sink.submit(batch)).accepted == 0
    with pytest.raises(ValueError):
        await sink.submit(
            batch.model_copy(update={"cursor": SyncCursor(stream="other")})
        )
    pack = ContentPack(connector="demo-agent", server=SERVER, entries=())
    assert (await sink.import_pack(pack)).pack_digest == pack.digest
    assert (await sink.import_pack(pack)).imported == 0
    assert list(sink.packs) == [pack.digest] and list(sink.batches) == [batch.digest]


async def test_in_memory_sink_passes_record_submission_tck() -> None:
    batch = RecordBatch(
        connector="demo-agent",
        mapping_reference="manifest:demo",
        records=(_record(title="t"),),
        cursor=SyncCursor(stream="demo", watermark="w"),
    )
    assert_conformant(await run_sink_suite(InMemorySink, batch))
