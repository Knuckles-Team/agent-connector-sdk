"""Runner supervision: commit ordering, fail-closed credentials, backoff, registry."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path

import anyio
import pytest
from fleet_fixtures import (
    FakeArchiveBox,
    FakeFreshRss,
    archivebox_snapshots,
    build_enumerated_archivebox_server,
    build_enumerated_freshrss_server,
    freshrss_items,
)
from runner_support import (
    FAST,
    KINDS,
    ListRegistry,
    RecordingSink,
    archivebox_descriptor,
    capture_runner_logs,
    eventually,
    freshrss_descriptor,
    in_process,
    logged,
    services,
)

from agent_connector_sdk.contracts import (
    ContentPack,
    IngestionReceipt,
    PackImportReceipt,
    RecordBatch,
)
from agent_connector_sdk.credentials.resolver import EnvironmentCredentialResolver
from agent_connector_sdk.ports.session import McpSession, TransportEndpoint
from agent_connector_sdk.runner.checkpoints import JsonFileCheckpointStore
from agent_connector_sdk.runner.descriptors import EndpointSpec
from agent_connector_sdk.runner.endpoints import CredentialEndpoints
from agent_connector_sdk.runner.errors import SinkReceiptError
from agent_connector_sdk.runner.plans import load_sync_adapters
from agent_connector_sdk.runner.provisioning import ProvisionOutcome, provision_content
from agent_connector_sdk.runner.supervisor import ConnectorSyncRunner
from agent_connector_sdk.runner.syncing import (
    SyncOutcome,
    SyncTarget,
    commit_page,
    sync_stream,
)
from agent_connector_sdk.runner.worker import ConnectorWorker
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

STREAM = "archivebox-snapshots"


class _LyingSink(InMemorySink):
    async def submit(self, batch: RecordBatch) -> IngestionReceipt:
        receipt = await super().submit(batch)
        return receipt.model_copy(update={"batch_digest": "sha256:another"})

    async def import_pack(self, pack: ContentPack) -> PackImportReceipt:
        receipt = await super().import_pack(pack)
        return receipt.model_copy(update={"pack_digest": "sha256:another"})


class _Transport:
    """Fails the first ``failures`` session opens, then delegates."""

    name = "test"

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.opened = 0

    def session(
        self, endpoint: TransportEndpoint
    ) -> AbstractAsyncContextManager[McpSession]:
        self.opened += 1
        if self.opened <= self.failures:
            raise ConnectionError("connector unreachable")
        return McpTransport().session(endpoint)


def _target(
    sink: InMemorySink, store: JsonFileCheckpointStore, max_pages: int
) -> SyncTarget:
    return SyncTarget(
        connector="archivebox-api",
        mapping_reference="manifest:archivebox-api",
        sink=sink,
        store=store,
        max_pages=max_pages,
    )


async def test_passes_commit_before_advancing(tmp_path: Path) -> None:
    store = JsonFileCheckpointStore(tmp_path)
    server = build_enumerated_archivebox_server(
        FakeArchiveBox(archivebox_snapshots(250))
    )
    adapter = load_sync_adapters(archivebox_descriptor())[STREAM]
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        outcome = await sync_stream(session, adapter, _target(InMemorySink(), store, 2))
        assert isinstance(outcome, SyncOutcome) and not outcome.exhausted
        assert (outcome.pages, outcome.records) == (2, 200)
        assert outcome.cursor == await store.committed_cursor("archivebox-api", STREAM)
        page = await adapter.extract(session, outcome.cursor)
        receipt = await commit_page(
            page,
            _target(InMemorySink(), store, 1),
            expected_previous_cursor=None,
        )
        assert receipt.accepted == 50 and page.exhausted
        provisioned = await provision_content(
            session,
            connector="archivebox-api",
            kinds=KINDS,
            sink=InMemorySink(),
            store=store,
        )
        assert isinstance(provisioned, ProvisionOutcome) and provisioned.changed


async def test_receipts_that_do_not_acknowledge_record_nothing(tmp_path: Path) -> None:
    store = JsonFileCheckpointStore(tmp_path)
    server = build_enumerated_archivebox_server(FakeArchiveBox(archivebox_snapshots(3)))
    adapter = load_sync_adapters(archivebox_descriptor())[STREAM]
    async with McpTransport().session(TransportEndpoint(in_process=server)) as session:
        with pytest.raises(SinkReceiptError):
            await sync_stream(session, adapter, _target(_LyingSink(), store, 5))
        with pytest.raises(SinkReceiptError):
            await provision_content(
                session,
                connector="archivebox-api",
                kinds=KINDS,
                sink=_LyingSink(),
                store=store,
            )
    assert await store.committed_cursor("archivebox-api", STREAM) is None
    assert await store.imported_pack_digest("archivebox-api") is None


async def test_unresolvable_credentials_never_open_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    monkeypatch.delenv("CONNECTOR_SYNC_TEST_TOKEN", raising=False)
    endpoint = EndpointSpec(
        url="https://freshrss.example.invalid/mcp",
        bearer_token="env://CONNECTOR_SYNC_TEST_TOKEN",
    )
    transport = _Transport(failures=0)
    built = services(
        RecordingSink(),
        JsonFileCheckpointStore(tmp_path),
        CredentialEndpoints(EnvironmentCredentialResolver()),
        transport=transport,
    )
    runner = ConnectorSyncRunner(
        ListRegistry(freshrss_descriptor(endpoint=endpoint)), built
    )
    assert await runner.run_once() == {"freshrss-agent": False}
    assert transport.opened == 0
    error = logged(caplog, "connector_failed")[0]["error"]
    assert "could not be resolved" in error and "CONNECTOR_SYNC_TEST_TOKEN" not in error


async def test_serve_backs_off_and_reconnects(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    sink = RecordingSink()
    endpoints = in_process(
        {
            "freshrss-agent": build_enumerated_freshrss_server(
                FakeFreshRss(freshrss_items(0, 2))
            )
        }
    )
    built = services(
        sink,
        JsonFileCheckpointStore(tmp_path),
        endpoints,
        transport=_Transport(failures=2),
    )
    worker = ConnectorWorker(freshrss_descriptor(), built, anyio.CapacityLimiter(1))
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(worker.serve)
        await eventually(lambda: sink.imports == 1)
        tasks.cancel_scope.cancel()
    assert [event["retry_in"] for event in logged(caplog, "connector_failed")] == [
        FAST.backoff_initial_seconds,
        FAST.backoff_initial_seconds * 2,
    ]


async def test_registry_changes_start_and_stop_workers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture_runner_logs(caplog)
    sink = RecordingSink()
    endpoints = in_process(
        {
            "freshrss-agent": build_enumerated_freshrss_server(
                FakeFreshRss(freshrss_items(0, 2))
            )
        }
    )
    registry = ListRegistry()
    runner = ConnectorSyncRunner(
        registry, services(sink, JsonFileCheckpointStore(tmp_path), endpoints)
    )
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(runner.run_forever)
        registry.descriptors.append(freshrss_descriptor())
        await eventually(lambda: sink.imports == 1)
        registry.broken = True
        await eventually(lambda: bool(logged(caplog, "registry_unreadable")))
        registry.broken = False
        registry.descriptors.clear()
        await eventually(lambda: bool(logged(caplog, "connector_stopped")))
        tasks.cancel_scope.cancel()
    assert logged(caplog, "connector_started")[0]["connector"] == "freshrss-agent"
