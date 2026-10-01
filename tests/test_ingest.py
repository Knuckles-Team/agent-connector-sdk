"""The knowledge-ingest facade: change sets become exact generated SourceIngest requests."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from epistemic_graph.generated.source_ingestion import (
    SourceIngestionMode,
    SourceIngestionReceipt,
    SourceIngestionRequest,
    SourceIngestStatus,
)

from agent_connector_sdk.ingest import (
    ChangeSet,
    Document,
    Entity,
    EntityRef,
    IngestBinding,
    IngestConflictError,
    IngestError,
    IngestUnavailableError,
    KnowledgeIngest,
    MediaAsset,
    Relationship,
    Withdrawal,
    aingest_changes,
    current_ingest,
    ingest_changes,
    install_ingest,
)
from agent_connector_sdk.ingest.channel import SourceIngestChannel
from agent_connector_sdk.ingest.engine import (
    INGEST_SCOPES,
    EngineSettings,
    connect_ingest,
)
from agent_connector_sdk.ingest.records import document_entity, media_entity
from agent_connector_sdk.ingest.request import build_request
from agent_connector_sdk.ingest.service import DEFAULT_ATTEMPTS, DEFAULT_SYNC_TIMEOUT_S
from agent_connector_sdk.ingest.transport import (
    EpistemicGraphIngestTransport,
    IngestTransport,
)
from agent_connector_sdk.testing.sinks import InMemorySink

BINDING = IngestBinding(connector="demo-mcp", stream="demo")


class _Transport:
    """An in-memory epistemic-graph: CAS checkpoints, receipts and Blob CAS."""

    def __init__(self, *, conflicts: int = 0) -> None:
        self.sink = InMemorySink()
        self.requests: list[SourceIngestionRequest] = []
        self.blobs: dict[str, bytes] = {}
        self.conflicts = conflicts

    async def submit(self, request: SourceIngestionRequest) -> SourceIngestionReceipt:
        self.requests.append(request)
        if self.conflicts:
            self.conflicts -= 1
            raise IngestConflictError("fixture race")
        return await self.sink.submit(request)

    async def source_status(self, connector: str, stream: str) -> SourceIngestStatus:
        return await self.sink.source_status(connector, stream)

    async def store_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.blobs[digest] = data
        return digest


def _changes() -> ChangeSet:
    return ChangeSet(
        entities=(Entity("demo:q:1", "Query", {"text": "q", "skip": None}),),
        documents=(Document("demo:r:1", "body", title="T", source_uri="https://x/1"),),
        relationships=(Relationship("demo:r:1", "demo:q:1", "resultOf"),),
    )


@pytest.fixture
def uninstalled() -> Iterator[None]:
    install_ingest(None)
    yield
    install_ingest(None)


def test_change_set_maps_to_exact_manifest_references() -> None:
    request = build_request(BINDING, _changes(), previous=None)
    assert [r.mapping_reference for r in request.records] == [
        "manifest:demo-mcp#schema_mappings/Query",
        "manifest:demo-mcp#schema_mappings/Document",
    ]
    assert request.records[0].payload == {"text": "q"}
    document = request.records[1].payload
    assert document["content_hash"] == hashlib.sha256(b"body").hexdigest()
    (edge,) = request.relationships
    assert edge.relation_reference == (
        "manifest:demo-mcp#resources/Document/relations/resultOf"
    )
    assert request.mode is SourceIngestionMode.DELTA
    assert request.expected_previous_checkpoint is None
    assert request.provider_checkpoint.position["sequence"] == 1
    provenance = request.records[0].provenance
    assert provenance.adapter_kind == BINDING.adapter_kind == "connector_push"
    assert provenance.server == BINDING.server_name == "demo-mcp"
    assert provenance.tool_schema_sha256 == BINDING.identity_digest()


def test_properties_are_sanitized_but_identities_are_not() -> None:
    changes = ChangeSet(
        entities=(
            Entity(
                "dns:record:10.0.0.9",
                "Record",
                {"rdata": "10.0.0.9", "owner_name": "Alice", "id": "10.0.0.9"},
            ),
        ),
        relationships=(
            Relationship("dns:record:10.0.0.9", "x", "in", {"note": "a@b.example"}),
        ),
    )
    request = build_request(BINDING, changes, previous=None)
    (record,) = request.records
    assert record.record_id == "dns:record:10.0.0.9"
    assert record.payload == {
        "rdata": "[REDACTED_IPV4]",
        "owner_name": "[REDACTED_PERSON]",
        "id": "10.0.0.9",
    }
    assert request.relationships[0].properties == {"note": "[REDACTED_EMAIL]"}
    raw = IngestBinding(connector="demo-mcp", stream="demo", sanitize=False)
    assert build_request(raw, changes, previous=None).records[0].payload["rdata"] == (
        "10.0.0.9"
    )


def test_relationship_source_type_is_never_guessed() -> None:
    orphan = ChangeSet(relationships=(Relationship("demo:x", "demo:y", "rel"),))
    with pytest.raises(IngestError, match="no node_type"):
        build_request(BINDING, orphan, previous=None)
    typed = ChangeSet(
        relationships=(
            Relationship(EntityRef("demo:x", "Item", stream="other"), "demo:y", "rel"),
        )
    )
    (edge,) = build_request(BINDING, typed, previous=None).relationships
    assert edge.source.stream == "other"
    assert edge.relation_reference.endswith("resources/Item/relations/rel")


def test_malformed_change_sets_fail_before_io() -> None:
    raw = IngestBinding(connector="demo-mcp", stream="demo", sanitize=False)
    with pytest.raises(IngestError, match="JSON"):
        build_request(
            raw,
            ChangeSet(entities=(Entity("a", "T", {"x": object()}),)),
            previous=None,
        )
    with pytest.raises(IngestError, match="id and a node_type"):
        build_request(BINDING, ChangeSet(entities=(Entity("", "T"),)), previous=None)
    with pytest.raises(IngestError, match="no text"):
        document_entity(BINDING, Document("d", ""))
    with pytest.raises(ValueError, match="live_ids"):
        ChangeSet(mode=SourceIngestionMode.RECONCILE)
    with pytest.raises(ValueError, match="stream"):
        IngestBinding(connector="demo-mcp", stream=" ")


def test_reconcile_and_withdrawals_are_explicit() -> None:
    reconcile = ChangeSet(
        entities=(Entity("a", "T"),),
        mode=SourceIngestionMode.RECONCILE,
        live_ids=("a",),
    )
    request = build_request(BINDING, reconcile, previous=None)
    assert [ref.record_id for ref in request.authoritative_live_ids or []] == ["a"]
    delta = ChangeSet(withdrawals=(Withdrawal("gone", "deleted upstream"),))
    (withdrawal,) = build_request(BINDING, delta, previous=None).withdrawals
    assert (withdrawal.entity.record_id, withdrawal.reason) == (
        "gone",
        "deleted upstream",
    )


async def test_submissions_chain_the_durable_checkpoint() -> None:
    transport = _Transport()
    service = KnowledgeIngest(transport)
    first = await service.submit(BINDING, _changes())
    second = await service.submit(BINDING, ChangeSet(entities=(Entity("b", "T"),)))
    assert first.affected_count == 2 and second.affected_count == 1
    earlier, later = transport.requests
    assert later.expected_previous_checkpoint == earlier.provider_checkpoint
    assert later.provider_checkpoint.position["sequence"] == 2


async def test_media_bytes_go_to_blob_storage_first() -> None:
    transport = _Transport()
    asset = MediaAsset(b"\x89PNG", "image/png", name="cover")
    await KnowledgeIngest(transport).submit(BINDING, ChangeSet(media=(asset,)))
    digest = hashlib.sha256(b"\x89PNG").hexdigest()
    assert transport.blobs == {digest: b"\x89PNG"}
    (record,) = transport.requests[0].records
    assert record.record_id == f"blob:{digest}"
    assert record.mapping_reference.endswith("schema_mappings/MediaAsset")
    assert record.payload == dict(media_entity(BINDING, asset, digest).properties)
    with pytest.raises(IngestError, match="no bytes"):
        await KnowledgeIngest(transport).submit(
            BINDING, ChangeSet(media=(MediaAsset(b"", "image/png"),))
        )


async def test_checkpoint_races_retry_then_give_up() -> None:
    transport = _Transport(conflicts=DEFAULT_ATTEMPTS - 1)
    receipt = await KnowledgeIngest(transport).submit(BINDING, _changes())
    assert receipt.affected_count == 2
    with pytest.raises(IngestConflictError):
        await KnowledgeIngest(_Transport(conflicts=9), attempts=2).submit(
            BINDING, _changes()
        )
    with pytest.raises(ValueError, match="attempts"):
        KnowledgeIngest(transport, attempts=0)


async def test_engine_rejections_surface_as_ingest_errors() -> None:
    class _Refusing(_Transport):
        async def submit(self, request: SourceIngestionRequest) -> Any:
            raise RuntimeError("CONNECTOR_SCHEMA_MAPPING_INVALID: ontology_class\nx")

    with pytest.raises(IngestError, match="CONNECTOR_SCHEMA_MAPPING_INVALID") as info:
        await KnowledgeIngest(_Refusing()).submit(BINDING, _changes())
    assert "\n" not in str(info.value)


def _engine_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def test_blocking_submission_runs_on_the_engine_loop(uninstalled: None) -> None:
    loop = _engine_loop()
    try:
        service = KnowledgeIngest(
            _Transport(), loop=loop, sync_timeout_s=DEFAULT_SYNC_TIMEOUT_S
        )
        install_ingest(service)
        assert current_ingest() is service
        assert ingest_changes(BINDING, _changes()).affected_count == 2
        with pytest.raises(IngestUnavailableError):
            KnowledgeIngest(_Transport()).submit_blocking(BINDING, _changes())
    finally:
        loop.call_soon_threadsafe(loop.stop)


async def test_async_callers_on_another_loop_are_bridged(uninstalled: None) -> None:
    loop = _engine_loop()
    try:
        install_ingest(KnowledgeIngest(_Transport(), loop=loop))
        receipt = await aingest_changes(BINDING, _changes())
        assert receipt.affected_count == 2
    finally:
        loop.call_soon_threadsafe(loop.stop)


async def test_blocking_submission_refuses_the_engine_thread() -> None:
    service = KnowledgeIngest(_Transport(), loop=asyncio.get_running_loop())
    with pytest.raises(IngestUnavailableError, match="own thread"):
        service.submit_blocking(BINDING, _changes())


def test_unconfigured_process_has_no_ingest(
    uninstalled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EPISTEMIC_GRAPH_ENDPOINT", raising=False)
    assert EngineSettings.from_settings() is None
    with pytest.raises(IngestUnavailableError, match="EPISTEMIC_GRAPH_ENDPOINT"):
        ingest_changes(BINDING, _changes())


def test_engine_settings_are_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPISTEMIC_GRAPH_ENDPOINT", "tcp://graph.example:9100")
    with pytest.raises(IngestUnavailableError, match="TENANT"):
        EngineSettings.from_settings()
    for key, value in {
        "EPISTEMIC_GRAPH_AUTH_SECRET_REF": "env://EG_SECRET",
        "EPISTEMIC_GRAPH_TENANT": "tenant-a",
        "EPISTEMIC_GRAPH_GRAPH": "kg",
    }.items():
        monkeypatch.setenv(key, value)
    settings = EngineSettings.from_settings()
    assert settings is not None
    with pytest.raises(IngestUnavailableError, match="loopback-only"):
        settings.address()
    assert settings.verified_context()["scopes"] == list(INGEST_SCOPES)
    local = EngineSettings("tcp://127.0.0.1:9100", "env://S", "t", "g")
    assert local.address() == {"tcp_addr": "127.0.0.1:9100"}
    assert EngineSettings("unix:///run/eg.sock", "env://S", "t", "g").address() == {
        "socket_path": "/run/eg.sock"
    }
    with pytest.raises(IngestUnavailableError, match="valid endpoint"):
        EngineSettings("http://x:1", "env://S", "t", "g").address()


def test_unreachable_or_misconfigured_engine_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_secret = EngineSettings("tcp://127.0.0.1:1", "env://EG_UNSET", "t", "g")
    monkeypatch.delenv("EG_UNSET", raising=False)
    with pytest.raises(IngestUnavailableError, match="misconfigured"):
        connect_ingest(missing_secret)
    monkeypatch.setenv("EG_SET", "secret-value")
    closed_port = EngineSettings("tcp://127.0.0.1:1", "env://EG_SET", "t", "g")
    with pytest.raises(IngestUnavailableError, match="unreachable"):
        connect_ingest(closed_port, timeout_s=5.0)


class _GeneratedClient:
    """A generated-client double speaking SourceIngest and Status."""

    def __init__(self, error: str | None = None) -> None:
        self.sink = InMemorySink()
        self.error = error

    async def _send(
        self, method: str, params: Any, graph: Any, *, idempotency_key: Any = None
    ) -> Any:
        if method == "SourceIngestStatus":
            status = await self.sink.source_status(
                params["connector"], params["stream"]
            )
            return status.model_dump(mode="json")
        if self.error:
            raise RuntimeError(self.error)
        request = SourceIngestionRequest.model_validate(params["request"])
        return (await self.sink.submit(request)).model_dump(mode="json")


async def test_epistemic_graph_transport_uses_the_generated_contract() -> None:
    transport = EpistemicGraphIngestTransport(_GeneratedClient())
    assert isinstance(transport, IngestTransport)
    receipt = await KnowledgeIngest(transport).submit(BINDING, _changes())
    assert receipt.affected_count == 2
    racing = EpistemicGraphIngestTransport(_GeneratedClient("CONFLICT: checkpoint"))
    with pytest.raises(IngestConflictError):
        await racing.submit(build_request(BINDING, _changes(), previous=None))
    failing = EpistemicGraphIngestTransport(_GeneratedClient("ACCESS_DENIED: no"))
    with pytest.raises(RuntimeError, match="ACCESS_DENIED"):
        await failing.submit(build_request(BINDING, _changes(), previous=None))
    with pytest.raises(ValueError, match="verified client"):
        SourceIngestChannel(None)


async def test_epistemic_graph_transport_has_no_media_storage_yet() -> None:
    """The generated client exposes no single-call blob store yet (see
    ``agent_connector_sdk.ingest.transport``'s module docstring); a change set
    with a media asset fails closed through ``KnowledgeIngest`` instead of
    raising a bare ``AttributeError`` against a client shape that does not
    exist.
    """
    transport = EpistemicGraphIngestTransport(_GeneratedClient())
    with pytest.raises(IngestUnavailableError, match="chunked upload"):
        await transport.store_blob(b"x")
    with pytest.raises(IngestError, match="media storage is not implemented"):
        await KnowledgeIngest(transport).submit(
            BINDING, ChangeSet(media=(MediaAsset(b"x", "text/plain"),))
        )
