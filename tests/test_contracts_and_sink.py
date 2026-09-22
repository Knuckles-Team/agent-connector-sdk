"""Generated EG ingestion contracts and SDK-owned authoring types."""

from __future__ import annotations

import pytest
from epistemic_graph.connector_pack import (
    ConnectorPackArchiveBuilder,
    ConnectorPackEntryContent,
    pack_digest,
)
from epistemic_graph.generated.connector_pack import (
    AgentLibraryMutationContext,
    McpCatalogSnapshotBinding,
    PackEntryKind,
    PackImportResultRejected,
    PackImportResultUnchanged,
)
from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionDisposition,
    SourceIngestionMode,
    SourceIngestionRequest,
    SourceRecord,
    SourceRecordProvenance,
)
from pydantic import ValidationError

import agent_connector_sdk.contracts as sdk_contracts
from agent_connector_sdk.artifacts.pack import CapturedConnectorPack
from agent_connector_sdk.contracts import (
    SEAM_SCHEMA_VERSION,
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    ServerIdentity,
    StreamDescriptor,
)
from agent_connector_sdk.ports.sink import Sink
from agent_connector_sdk.sinks.epistemic_graph import (
    EpistemicGraphSink,
    PackImportAuthorityResolver,
)
from agent_connector_sdk.testing.results import assert_conformant
from agent_connector_sdk.testing.sinks import InMemorySink, run_sink_suite

SERVER = ServerIdentity(name="demo-mcp", version="1.0.0")
_DIGEST = "a" * 64


def test_pack_import_authority_resolver_is_public() -> None:
    assert PackImportAuthorityResolver is not None


def test_sdk_does_not_redeclare_generated_graph_boundary_models() -> None:
    copied_names = {
        "ArtifactEntry",
        "ContentPack",
        "IngestionReceipt",
        "PackImportReceipt",
        "PackRecord",
        "RecordBatch",
        "SourceRecord",
        "SyncCursor",
    }
    locally_owned = {
        name
        for name, value in vars(sdk_contracts).items()
        if getattr(value, "__module__", "") == sdk_contracts.__name__
    }
    assert copied_names.isdisjoint(locally_owned)
    assert copied_names.isdisjoint(sdk_contracts.__all__)


def _catalog() -> McpCatalogSnapshotBinding:
    return McpCatalogSnapshotBinding(
        configuration_revision=7,
        catalog_generation=11,
        snapshot_digest=_DIGEST,
        child_connection_generation=3,
        authorization_scope_digest="b" * 64,
    )


def _mutation_context() -> AgentLibraryMutationContext:
    return AgentLibraryMutationContext(
        request_id=1,
        principal="principal-a",
        caller_principal="caller-a",
        attempt_nonce="07" * 32,
        tenant_id="tenant-a",
        actor_scope="scope-a",
        purpose_id="purpose-a",
        policy_revision="policy-1",
        policy_digest="sha256:" + "c" * 64,
        policy_decision_id="decision-1",
        idempotency_key="caller-value",
        expected_revision=1,
        trace_id="trace-1",
        created_at_ms=1_700_000_000_000,
    )


def _pack() -> CapturedConnectorPack:
    archive = ConnectorPackArchiveBuilder.build(
        ConnectorPackEntryContent(
            kind=PackEntryKind.MCP_SERVER,
            uri="mcp-server://demo-agent",
            name="demo-agent",
            media_type="application/json",
            body=b'{"name":"demo-agent"}',
        ),
        (),
    )
    return CapturedConnectorPack(
        connector="demo-agent",
        server_package_version="1.0.0",
        archive=archive,
        resource_uris=frozenset(),
    )


async def _pack_authority(
    connector: str,
) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
    raise AssertionError(f"pack authority unexpectedly requested for {connector}")


class _GeneratedClient:
    def __init__(
        self, *, mismatch: bool = False, status_mismatch: bool = False
    ) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.sink = InMemorySink()
        self.mismatch = mismatch
        self.status_mismatch = status_mismatch

    async def _send(
        self,
        method: str,
        params: dict[str, object] | None,
        graph: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        assert params is not None and graph is None
        if method == "SourceIngestStatus":
            status = await self.sink.source_status(
                str(params["connector"]), str(params["stream"])
            )
            payload = status.model_dump(mode="json")
            if self.status_mismatch:
                payload["stream"] = "other"
            return payload
        assert method == "SourceIngest"
        request = SourceIngestionRequest.model_validate(params["request"])
        receipt = await self.sink.submit(request)
        self.calls.append((method, idempotency_key))
        payload = receipt.model_dump(mode="json")
        if self.mismatch:
            payload["batch_digest"] = "f" * 64
        return payload


class _PackClient:
    def __init__(
        self,
        *,
        reject: bool = False,
        mismatch: bool = False,
        head_digest: str | None = None,
        conflict_once: bool = False,
    ) -> None:
        self.reject = reject
        self.mismatch = mismatch
        self.head_digest = head_digest
        self.conflict_once = conflict_once
        self.calls: list[tuple[str, dict[str, object] | None, str | None]] = []

    async def _send(
        self,
        method: str,
        params: dict[str, object] | None,
        graph: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> object:
        self.calls.append((method, params, idempotency_key))
        if method == "ConnectorPack" and params is not None:
            return self._connector_pack(params)
        return self._blob(method, params, graph)

    def _connector_pack(self, params: dict[str, object]) -> object:
        operation = params["op"]
        assert isinstance(operation, dict)
        return (
            self._status() if operation["op"] == "status" else self._import(operation)
        )

    def _status(self) -> dict[str, object]:
        response: dict[str, object] = {
            "schema_version": 2,
            "tenant_id": "tenant-a",
            "connector": "demo-agent",
            "members": {"published": 0, "withdrawn": 0, "retired": 0},
            "warnings": [],
            "projection": {"projection": "none"},
        }
        if self.head_digest is not None:
            response["head"] = {
                "binding_revision": 4,
                "catalog": _catalog().model_dump(mode="json"),
                "committed_at_ms": 1_700_000_000_000,
                "pack_digest": self.head_digest,
                "record_id": "pack:demo-agent:4",
                "server_package_version": "1.0.0",
            }
        return response

    def _import(self, operation: dict[str, object]) -> object:
        if self.reject:
            return {
                "result": "rejected",
                "pack_digest": None,
                "violations": [{"code": "MALFORMED_INDEX", "detail": "fixture"}],
                "budget_exhausted": False,
            }
        request = operation["request"]
        assert isinstance(request, dict)
        index = request["index"]
        assert isinstance(index, dict)
        if self.conflict_once:
            self.conflict_once = False
            raise RuntimeError("PACK_HEAD_CONFLICT: fixture")
        digest = "f" * 64 if self.mismatch else index["pack_digest"]
        return {"result": "unchanged", "pack_digest": digest, "binding_revision": 4}

    @staticmethod
    def _blob(method: str, params: object, graph: object) -> object:
        if method == "BlobBegin":
            return 91
        if method == "BlobChunkPut":
            return 1
        if method == "BlobCommit":
            return "blob-manifest-a"
        raise AssertionError((method, params, graph))


def _provenance(tool: str = "reader") -> SourceRecordProvenance:
    return SourceRecordProvenance(
        connector="demo-agent",
        adapter_kind="mcp_tool",
        server="demo-mcp",
        tool=tool,
        tool_schema_sha256="a" * 64,
        source_uri="mcp-tool://demo-mcp/reader/1",
    )


def _record(**payload: object) -> SourceRecord:
    return SourceRecord(
        stream="demo",
        record_id="1",
        mapping_reference="manifest:demo-agent#schema_mappings/Document",
        payload=dict(payload),
        provenance=_provenance(),
    )


def _batch(
    *records: SourceRecord,
    checkpoint: SourceCheckpoint | None = None,
    expected: SourceCheckpoint | None = None,
) -> SourceIngestionRequest:
    return SourceIngestionRequest(
        connector="demo-agent",
        mode=SourceIngestionMode.FULL,
        strict_schema=True,
        records=list(records),
        relationships=[],
        provider_checkpoint=checkpoint or SourceCheckpoint(stream="demo", position={}),
        expected_previous_checkpoint=expected,
        authoritative_live_ids=None,
        empty_authoritative_approval=None,
        withdrawals=[],
    )


def test_generated_provenance_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourceRecordProvenance(
            connector="demo-agent",
            adapter_kind="mcp_tool",
            server="s",
            tool="t",
            tool_schema_sha256="a" * 64,
            source_uri="u",
            copied_sdk_field="forbidden",
        )
    with pytest.raises(ValidationError):
        SourceRecordProvenance(
            connector="demo-agent",
            adapter_kind="mcp_tool",
            server="s",
            tool="t",
            tool_schema_sha256="not-a-digest",
            source_uri="u",
        )


def test_batch_digest_changes_with_checkpoint() -> None:
    record = _record(title="t")
    batch = _batch(record)
    advanced = batch.model_copy(
        update={
            "provider_checkpoint": SourceCheckpoint(
                stream="demo", position={}, watermark="w"
            )
        }
    )
    assert batch.canonical_digest() != advanced.canonical_digest()
    page = RecordPage(
        records=(record,),
        mode=SourceIngestionMode.FULL,
        strict_schema=True,
        checkpoint=batch.provider_checkpoint,
        exhausted=True,
    )
    assert page.exhausted


def test_batch_digest_binds_expected_previous_checkpoint() -> None:
    batch = _batch(
        _record(title="t"),
        checkpoint=SourceCheckpoint(stream="demo", position={"page": 2}),
        expected=SourceCheckpoint(stream="demo", position={"page": 1}),
    )
    initial = batch.model_copy(update={"expected_previous_checkpoint": None})
    assert batch.canonical_digest() != initial.canonical_digest()


def test_batch_digest_binds_raw_provenance() -> None:
    record = _record(title="t")
    moved = record.model_copy(update={"provenance": _provenance(tool="other")})
    first = _batch(record)
    second = first.model_copy(update={"records": [moved]})
    assert first.canonical_digest() != second.canonical_digest()


@pytest.mark.parametrize(
    ("records", "checkpoint", "message"),
    [
        (
            (_record(title="one"), _record(title="two")),
            SourceCheckpoint(stream="demo", position={}),
            "record identities must be unique",
        ),
        (
            (_record(title="one").model_copy(update={"stream": "other"}),),
            SourceCheckpoint(stream="demo", position={}),
            "checkpoint stream",
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
            SourceCheckpoint(stream="demo", position={}),
            "batch connector",
        ),
    ],
)
async def test_record_batch_refuses_ambiguous_commit_scope(
    records: tuple[SourceRecord, ...], checkpoint: SourceCheckpoint, message: str
) -> None:
    batch = _batch(*records, checkpoint=checkpoint)
    with pytest.raises(ValueError, match=message):
        await InMemorySink().submit(batch)


def test_small_descriptors() -> None:
    assert CapabilityDescriptor(kind="k").schema_version == SEAM_SCHEMA_VERSION
    assert StreamDescriptor(stream="s", tool="t", schema_sha256="x").tool == "t"
    report = ReconciliationReport(
        stream="s", missing_from_source=("1",), unknown_to_sink=()
    )
    assert report.missing_from_source == ("1",)
    with pytest.raises(ValidationError):
        SourceCheckpoint.model_validate({"stream": "s", "position": {}, "copied": True})


async def test_epistemic_graph_sink_uses_generated_source_ingest_end_to_end() -> None:
    client = _GeneratedClient()
    sink = EpistemicGraphSink(client, _pack_authority)
    batch = _batch(
        _record(title="t"),
        checkpoint=SourceCheckpoint(stream="demo", position={"page": 2}),
    )
    first = await sink.submit(batch)
    replay = await sink.submit(batch)
    expected_key = f"source-ingest:demo-agent:{batch.canonical_digest()}"
    assert client.calls == [
        ("SourceIngest", expected_key),
        ("SourceIngest", expected_key),
    ]
    assert first.disposition is SourceIngestionDisposition.COMMITTED
    assert replay.disposition is SourceIngestionDisposition.REPLAYED
    assert (
        first.accepted_checkpoint
        == replay.accepted_checkpoint
        == batch.provider_checkpoint
    )


async def test_epistemic_graph_sink_rejects_mismatched_generated_receipt() -> None:
    sink = EpistemicGraphSink(_GeneratedClient(mismatch=True), _pack_authority)
    batch = _batch()
    with pytest.raises(ValueError, match="does not bind"):
        await sink.submit(batch)


async def test_epistemic_graph_sink_rejects_mismatched_status() -> None:
    sink = EpistemicGraphSink(_GeneratedClient(status_mismatch=True), _pack_authority)
    with pytest.raises(ValueError, match="does not bind"):
        await sink.source_status("demo-agent", "demo")


async def test_epistemic_graph_sink_imports_with_live_generated_authority() -> None:
    resolved: list[str] = []

    async def authority(
        connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        resolved.append(connector)
        return _catalog(), _mutation_context()

    client = _PackClient()
    result = await EpistemicGraphSink(client, authority).import_pack(_pack())
    assert isinstance(result, PackImportResultUnchanged)
    assert resolved == ["demo-agent"]
    methods = [method for method, _, _ in client.calls]
    assert methods == [
        "ConnectorPack",
        "BlobBegin",
        "BlobChunkPut",
        "BlobCommit",
        "ConnectorPack",
    ]
    import_call = client.calls[-1]
    operation = import_call[1]["op"]
    assert operation["request"]["index"]["catalog"] == _catalog().model_dump(
        mode="json"
    )
    assert import_call[2].startswith("connector-pack:demo-agent:import:")


async def test_epistemic_graph_sink_resolves_pack_authority_for_every_import() -> None:
    resolved: list[str] = []

    async def authority(
        connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        resolved.append(connector)
        return _catalog(), _mutation_context()

    pack = _pack()
    digest = pack_digest(
        pack.connector, _catalog(), pack.archive.server, pack.archive.entries
    )
    sink = EpistemicGraphSink(_PackClient(head_digest=digest), authority)
    await sink.import_pack(pack)
    await sink.import_pack(pack)
    assert resolved == ["demo-agent", "demo-agent"]


async def test_epistemic_graph_sink_preserves_typed_pack_rejection() -> None:
    async def authority(
        _connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        return _catalog(), _mutation_context()

    result = await EpistemicGraphSink(_PackClient(reject=True), authority).import_pack(
        _pack()
    )
    assert isinstance(result, PackImportResultRejected)
    assert result.violations[0].code.value == "MALFORMED_INDEX"


async def test_epistemic_graph_sink_replays_matching_pack_without_upload() -> None:
    async def authority(
        _connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        return _catalog(), _mutation_context()

    pack = _pack()
    digest = pack_digest(
        pack.connector, _catalog(), pack.archive.server, pack.archive.entries
    )
    client = _PackClient(head_digest=digest)
    result = await EpistemicGraphSink(client, authority).import_pack(pack)
    assert isinstance(result, PackImportResultUnchanged)
    assert result.pack_digest == digest and result.binding_revision == 4
    assert [method for method, _, _ in client.calls] == ["ConnectorPack"]


async def test_epistemic_graph_sink_retries_one_pack_head_conflict() -> None:
    async def authority(
        _connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        return _catalog(), _mutation_context()

    client = _PackClient(conflict_once=True)
    result = await EpistemicGraphSink(client, authority).import_pack(_pack())
    assert isinstance(result, PackImportResultUnchanged)
    imports = [
        call
        for call in client.calls
        if call[0] == "ConnectorPack" and call[1]["op"]["op"] == "import"
    ]
    assert len(imports) == 2
    assert imports[0][2] == imports[1][2]


async def test_epistemic_graph_sink_rejects_mismatched_pack_digest() -> None:
    async def authority(
        _connector: str,
    ) -> tuple[McpCatalogSnapshotBinding, AgentLibraryMutationContext]:
        return _catalog(), _mutation_context()

    with pytest.raises(ValueError, match="does not bind"):
        await EpistemicGraphSink(_PackClient(mismatch=True), authority).import_pack(
            _pack()
        )


async def test_in_memory_sink_acknowledges_once() -> None:
    sink = InMemorySink()
    assert isinstance(sink, Sink)
    batch = _batch(
        _record(title="t"),
        checkpoint=SourceCheckpoint(stream="demo", position={}, watermark="w"),
    )
    first = await sink.submit(batch)
    assert (first.affected_count, first.batch_digest, first.accepted_checkpoint) == (
        1,
        batch.canonical_digest(),
        batch.provider_checkpoint,
    )
    assert (await sink.submit(batch)).affected_count == 0
    with pytest.raises(ValueError):
        await sink.submit(
            batch.model_copy(
                update={
                    "provider_checkpoint": SourceCheckpoint(stream="other", position={})
                }
            )
        )
    pack = _pack()
    first_pack = await sink.import_pack(pack)
    replayed_pack = await sink.import_pack(pack)
    assert first_pack.receipt.pack_digest == replayed_pack.pack_digest
    assert list(sink.packs) == [first_pack.receipt.pack_digest]
    assert list(sink.batches) == [batch.canonical_digest()]


async def test_in_memory_sink_passes_record_submission_tck() -> None:
    batch = _batch(
        _record(title="t"),
        checkpoint=SourceCheckpoint(stream="demo", position={}, watermark="w"),
    )
    assert_conformant(await run_sink_suite(InMemorySink, batch))
