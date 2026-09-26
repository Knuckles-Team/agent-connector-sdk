"""C5 synthetic source: served action contract and durable replay."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAuthorizationMode,
)
from fastmcp import Client
from fastmcp.server.auth import AccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from agent_connector_sdk.certify.listing import list_server_tools
from agent_connector_sdk.contracts import ServerIdentity
from agent_connector_sdk.manifest.loader import load_manifest
from agent_connector_sdk.manifest.tool_schema import (
    canonical_input_schema,
    canonical_output_schema,
    compatibility_fingerprint,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.testing.synthetic_writeback import (
    LiveSyntheticWriteBackEvidence,
    SyntheticWriteBackResult,
    build_synthetic_writeback_eg_server,
    build_synthetic_writeback_server,
    build_synthetic_writeback_test_namespace_server,
    run_live_synthetic_writeback_acceptance,
    seed_synthetic_writeback_test_source,
    serve_synthetic_writeback_test_namespace,
    verify_synthetic_writeback_source_effect,
)
from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.transports.mcp import McpTransport
from agent_connector_sdk.writeback.connector import DurableWritableConnector
from agent_connector_sdk.writeback.durable_ledger import FileWriteBackLedger
from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport
from agent_connector_sdk.writeback.epistemic_graph import EpistemicGraphWriteBackLedger
from agent_connector_sdk.writeback.errors import WriteBackPersistenceError

MANIFEST = Path(__file__).parent / "synthetic_writeback_package/connector_manifest.yml"


class _TenantEgClient:
    """In-process EG wire stand-in; persists behind generated operations."""

    def __init__(
        self, root: Path, tenant_id: str, principal: str = "principal:fixture"
    ) -> None:
        self.ledger = FileWriteBackLedger(root)
        self.tenant_id = tenant_id
        self.principal = principal
        self.methods: list[str] = []

    async def _send(
        self,
        method: str,
        params: dict[str, object],
        graph: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> object:
        assert method == "WriteBack" and graph == "graph:c5"
        self.methods.append(method)
        op = params["op"]
        assert isinstance(op, dict)
        name = op["op"]
        if name == "create":
            change = SourceChangeSet.model_validate(op["change_set"])
            assert change.tenant_id == self.tenant_id
            assert change.actor == self.principal
            result = await self.ledger.create(change)
        elif name == "get":
            assert op["tenant_id"] == self.tenant_id
            result = await self.ledger.get(op["tenant_id"], op["change_set_id"])
        elif name == "record_attempt":
            attempt = WriteBackAttempt.model_validate(op["attempt"])
            assert attempt.tenant_id == self.tenant_id
            result = await self.ledger.record_attempt(attempt)
        elif name == "record_reconciliation":
            observation = ReconciliationObservation.model_validate(op["observation"])
            assert observation.tenant_id == self.tenant_id
            result = await self.ledger.record_reconciliation(observation)
        else:
            assert name == "receipts" and op["tenant_id"] == self.tenant_id
            result = await self.ledger.receipts(
                op["tenant_id"],
                op["change_set_id"],
                after_sequence=op.get("after_sequence"),
                limit=op["limit"],
            )
        assert result is not None
        return result.model_dump(mode="json")


class _KillAfterSourceEffect(FileWriteBackTransport):
    async def apply(
        self, change_set: SourceChangeSet, expected_version: str
    ) -> WriteBackAttempt:
        attempt = await super().apply(change_set, expected_version)
        os.kill(os.getpid(), signal.SIGKILL)
        return attempt  # pragma: no cover - process is dead


def _apply_until_killed(directory: str, payload: dict[str, object]) -> None:
    async def run() -> None:
        root = Path(directory)
        change = SourceChangeSet.model_validate(payload)
        eg = _TenantEgClient(root / "eg", change.tenant_id)
        connector = DurableWritableConnector(
            change.connector_id,
            _KillAfterSourceEffect(root / "source"),
            EpistemicGraphWriteBackLedger(eg, graph="graph:c5"),
        )
        await connector.apply(change)

    asyncio.run(run())


class _LiveFixtureSession:
    def __init__(self, client: Client[Any]) -> None:
        self._client = client

    async def server_identity(self) -> ServerIdentity:
        return ServerIdentity(name="synthetic-writeback", version="1.0.0")

    async def call_tool(self, name: str, arguments: dict[str, str]) -> object:
        response = await self._client.call_tool(name, arguments)
        return response.structured_content


class _LiveFixtureTransport(McpTransport):
    def __init__(self, server: Any) -> None:
        self._server = server

    @asynccontextmanager
    async def session(
        self, endpoint: TransportEndpoint
    ) -> AsyncIterator[_LiveFixtureSession]:
        assert endpoint.url
        async with Client(self._server) as client:
            yield _LiveFixtureSession(client)


def _change_set() -> SourceChangeSet:
    change = make_writeback_fixture().change_set.model_copy(
        update={
            "tenant_id": "tenant-c5",
            "connector_id": "synthetic-writeback",
            "source_instance_id": "synthetic-source",
        }
    )
    return change.model_copy(update={"change_set_digest": change.canonical_digest()})


async def test_synthetic_action_manifest_matches_served_schemas(tmp_path: Path) -> None:
    ledger = FileWriteBackLedger(tmp_path / "ledger")
    server = build_synthetic_writeback_server(
        ledger, tmp_path / "source", tenant_id="tenant-c5"
    )
    listing = await list_server_tools(
        McpTransport(), TransportEndpoint(in_process=server), timeout_seconds=10
    )
    assert len(listing.tools) == 1
    tool = listing.tools[0]
    manifest = load_manifest(MANIFEST)
    action = manifest.actions[0]
    assert (manifest.connector, action.id, action.requires_approval) == (
        "synthetic-writeback",
        tool.name,
        True,
    )
    input_schema = canonical_input_schema(tool, include_presentation=False)
    output_schema = canonical_output_schema(tool, include_presentation=False)
    assert input_schema["properties"]["action"]["enum"] == [
        "apply",
        "dry_run",
        "reconcile",
    ]
    pin_file = MANIFEST.parent / "connectors/tool_schema_fingerprints.json"
    pins = json.loads(pin_file.read_text())
    assert pins["connector"] == manifest.connector
    assert pins["tools"][tool.name] == compatibility_fingerprint(
        tool.name, input_schema, output_schema
    )


async def test_synthetic_served_dry_run_apply_and_restart_replay(
    tmp_path: Path,
) -> None:
    change = _change_set()
    ledger = FileWriteBackLedger(tmp_path / "ledger")
    await ledger.create(change)
    source = FileWriteBackTransport(tmp_path / "source")
    source.seed(change.entity_id, "v1", {"status": "new"})

    server = build_synthetic_writeback_server(
        ledger, tmp_path / "source", tenant_id="tenant-c5"
    )
    args = {"tenant_id": "tenant-c5", "change_set_id": change.change_set_id}
    async with Client(server) as client:
        preview = await client.call_tool(
            "synthetic_writeback", {"action": "dry_run", **args}
        )
        assert (
            SyntheticWriteBackResult.model_validate(
                preview.structured_content
            ).receipt_id
            is None
        )
        assert (await source.read_current(change)).source_version == "v1"
        applied = await client.call_tool(
            "synthetic_writeback", {"action": "apply", **args}
        )
        first = SyntheticWriteBackResult.model_validate(applied.structured_content)
        assert first.receipt_id

    restarted = build_synthetic_writeback_server(
        FileWriteBackLedger(tmp_path / "ledger"),
        tmp_path / "source",
        tenant_id="tenant-c5",
    )
    async with Client(restarted) as client:
        replay = await client.call_tool(
            "synthetic_writeback", {"action": "apply", **args}
        )
        second = SyntheticWriteBackResult.model_validate(replay.structured_content)
        assert second.server_instance_id != first.server_instance_id
        assert (
            second.model_copy(update={"server_instance_id": first.server_instance_id})
            == first
        )
        foreign = await client.call_tool(
            "synthetic_writeback",
            {
                "action": "apply",
                "tenant_id": "tenant-other",
                "change_set_id": change.change_set_id,
            },
            raise_on_error=False,
        )
        assert foreign.is_error
    assert (await source.read_current(change)).source_version == "v1+1"
    page = await ledger.receipts(change.tenant_id, change.change_set_id)
    assert len(page.receipts) == 1
    assert page.receipts[0].receipt.receipt_id == first.receipt_id


async def test_synthetic_served_denied_change_set_never_mutates(tmp_path: Path) -> None:
    change = _change_set()
    denied = change.model_copy(
        update={
            "authorization": change.authorization.model_copy(
                update={"authorized": False}
            )
        }
    )
    denied = denied.model_copy(update={"change_set_digest": denied.canonical_digest()})
    ledger = FileWriteBackLedger(tmp_path / "ledger")
    await ledger.create(denied)
    source = FileWriteBackTransport(tmp_path / "source")
    source.seed(denied.entity_id, "v1", {"status": "new"})
    server = build_synthetic_writeback_server(
        ledger, tmp_path / "source", tenant_id="tenant-c5"
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "synthetic_writeback",
            {
                "action": "apply",
                "tenant_id": denied.tenant_id,
                "change_set_id": denied.change_set_id,
            },
            raise_on_error=False,
        )
        assert result.is_error
    assert (await source.read_current(denied)).source_version == "v1"
    assert not (await ledger.receipts(denied.tenant_id, denied.change_set_id)).receipts


async def test_synthetic_eg_adapter_serves_receipt_after_restart(
    tmp_path: Path,
) -> None:
    change = _change_set()
    eg = _TenantEgClient(tmp_path / "eg", "tenant-c5")
    ledger = EpistemicGraphWriteBackLedger(eg, graph="graph:c5")
    assert await ledger.create(change) == change
    source = FileWriteBackTransport(tmp_path / "source")
    source.seed(change.entity_id, "v1", {"status": "new"})
    args = {
        "action": "apply",
        "tenant_id": "tenant-c5",
        "change_set_id": change.change_set_id,
    }

    server = build_synthetic_writeback_eg_server(
        eg, tmp_path / "source", graph="graph:c5", tenant_id="tenant-c5"
    )
    async with Client(server) as client:
        first = SyntheticWriteBackResult.model_validate(
            (await client.call_tool("synthetic_writeback", args)).structured_content
        )
    restarted_eg = _TenantEgClient(tmp_path / "eg", "tenant-c5")
    restarted = build_synthetic_writeback_eg_server(
        restarted_eg, tmp_path / "source", graph="graph:c5", tenant_id="tenant-c5"
    )
    async with Client(restarted) as client:
        second = SyntheticWriteBackResult.model_validate(
            (await client.call_tool("synthetic_writeback", args)).structured_content
        )
    assert first.server_instance_id != second.server_instance_id
    assert (
        second.model_copy(update={"server_instance_id": first.server_instance_id})
        == first
    )
    assert first.receipt_id
    assert (await source.read_current(change)).source_version == "v1+1"
    page = await EpistemicGraphWriteBackLedger(restarted_eg, graph="graph:c5").receipts(
        change.tenant_id, change.change_set_id
    )
    assert len(page.receipts) == 1
    assert page.receipts[0].receipt.receipt_id == first.receipt_id
    assert eg.methods and restarted_eg.methods


async def test_test_namespace_requires_authenticated_granted_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = _change_set()
    eg = _TenantEgClient(tmp_path / "eg", "tenant-c5")
    await EpistemicGraphWriteBackLedger(eg, graph="graph:c5").create(change)
    source = FileWriteBackTransport(tmp_path / "source")
    source.seed(change.entity_id, "v1", {"status": "new"})
    monkeypatch.setenv(
        "C5_STATIC_TOKENS",
        json.dumps(
            {
                "t" * 32: {
                    "client_id": "release-qual-c5",
                    "scopes": ["writeback:synthetic"],
                }
            }
        ),
    )
    options = [
        "--transport",
        "streamable-http",
        "--auth-type",
        "static",
        "--static-tokens-ref",
        "env://C5_STATIC_TOKENS",
    ]
    server, network = build_synthetic_writeback_test_namespace_server(
        eg,
        tmp_path / "source",
        graph="graph:c5",
        tenant_id="tenant-c5",
        client_id="release-qual-c5",
        command_args=options,
    )
    assert network.auth_type == "static"
    assert network.transport == "streamable-http"
    assert network.fastmcp_run_kwargs()["middleware"]
    async with Client(server) as client:
        refused = await client.call_tool(
            "synthetic_writeback",
            {
                "action": "apply",
                "tenant_id": "tenant-c5",
                "change_set_id": change.change_set_id,
            },
            raise_on_error=False,
        )
    assert refused.is_error
    assert (await source.read_current(change)).source_version == "v1"
    assert not eg.methods[1:]
    for caller, scopes in (
        ("another-client", ["writeback:synthetic"]),
        ("release-qual-c5", []),
    ):
        access = AccessToken(token="t" * 32, client_id=caller, scopes=scopes)
        reset = auth_context_var.set(AuthenticatedUser(access))
        try:
            async with Client(server) as client:
                refused = await client.call_tool(
                    "synthetic_writeback",
                    {
                        "action": "apply",
                        "tenant_id": "tenant-c5",
                        "change_set_id": change.change_set_id,
                    },
                    raise_on_error=False,
                )
            assert refused.is_error
        finally:
            auth_context_var.reset(reset)
    assert (await source.read_current(change)).source_version == "v1"
    assert not eg.methods[1:]
    access = AccessToken(
        token="t" * 32,
        client_id="release-qual-c5",
        scopes=["writeback:synthetic"],
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        async with Client(server) as client:
            applied = await client.call_tool(
                "synthetic_writeback",
                {
                    "action": "apply",
                    "tenant_id": "tenant-c5",
                    "change_set_id": change.change_set_id,
                },
            )
        first = SyntheticWriteBackResult.model_validate(applied.structured_content)
        assert first.receipt_id

        restarted_eg = _TenantEgClient(tmp_path / "eg", "tenant-c5")
        restarted, restarted_network = build_synthetic_writeback_test_namespace_server(
            restarted_eg,
            tmp_path / "source",
            graph="graph:c5",
            tenant_id="tenant-c5",
            client_id="release-qual-c5",
            command_args=options,
        )
        assert restarted_network == network
        async with Client(restarted) as client:
            replay = await client.call_tool(
                "synthetic_writeback",
                {
                    "action": "apply",
                    "tenant_id": "tenant-c5",
                    "change_set_id": change.change_set_id,
                },
            )
        replayed = SyntheticWriteBackResult.model_validate(replay.structured_content)
        assert replayed.server_instance_id != first.server_instance_id
        assert (
            replayed.model_copy(update={"server_instance_id": first.server_instance_id})
            == first
        )
    finally:
        auth_context_var.reset(reset)
    assert (await source.read_current(change)).source_version == "v1+1"
    page = await EpistemicGraphWriteBackLedger(restarted_eg, graph="graph:c5").receipts(
        change.tenant_id, change.change_set_id
    )
    assert len(page.receipts) == 1
    receipt = page.receipts[0].receipt
    assert receipt.receipt_id == first.receipt_id
    assert receipt.authorization == change.authorization
    assert receipt.actor == change.actor


def test_test_namespace_rejects_stdio_or_missing_auth(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="authenticated streamable HTTP"):
        build_synthetic_writeback_test_namespace_server(
            object(),
            tmp_path,
            graph="graph:c5",
            tenant_id="tenant-c5",
            client_id="release-qual-c5",
            command_args=[],
        )
    with pytest.raises(ValueError, match="authenticated streamable HTTP"):
        build_synthetic_writeback_test_namespace_server(
            object(),
            tmp_path,
            graph="graph:c5",
            tenant_id="tenant-c5",
            client_id="release-qual-c5",
            command_args=["--transport", "streamable-http", "--auth-type", "none"],
        )


@pytest.mark.parametrize("field", ["graph", "tenant_id", "client_id"])
def test_test_namespace_rejects_blank_authority_binding(
    tmp_path: Path, field: str
) -> None:
    binding = {
        "graph": "graph:c5",
        "tenant_id": "tenant-c5",
        "client_id": "release-qual-c5",
    }
    binding[field] = "   "
    with pytest.raises(ValueError, match="graph, tenant_id and client_id"):
        build_synthetic_writeback_test_namespace_server(
            object(), tmp_path, command_args=[], **binding
        )


async def test_generated_eg_writeback_recovers_after_process_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = _change_set()
    eg = _TenantEgClient(tmp_path / "eg", change.tenant_id)
    ledger = EpistemicGraphWriteBackLedger(eg, graph="graph:c5")
    await ledger.create(change)
    source = FileWriteBackTransport(tmp_path / "source")
    source.seed(change.entity_id, "v1", {"status": "new"})
    child = multiprocessing.get_context("spawn").Process(
        target=_apply_until_killed,
        args=(str(tmp_path), change.model_dump(mode="json")),
    )
    child.start()
    child.join(timeout=30)
    if child.is_alive():
        child.kill()
        child.join(timeout=5)
    assert child.exitcode == -signal.SIGKILL
    assert (await source.read_current(change)).source_version == "v1+1"
    assert not (await ledger.receipts(change.tenant_id, change.change_set_id)).receipts

    token = "t" * 32
    monkeypatch.setenv(
        "C5_STATIC_TOKENS",
        json.dumps(
            {
                token: {
                    "client_id": "release-qual-c5",
                    "scopes": ["writeback:synthetic"],
                }
            }
        ),
    )
    restarted_eg = _TenantEgClient(tmp_path / "eg", change.tenant_id)
    server, _ = build_synthetic_writeback_test_namespace_server(
        restarted_eg,
        tmp_path / "source",
        graph="graph:c5",
        tenant_id=change.tenant_id,
        client_id="release-qual-c5",
        command_args=[
            "--transport",
            "streamable-http",
            "--auth-type",
            "static",
            "--static-tokens-ref",
            "env://C5_STATIC_TOKENS",
        ],
    )
    access = AccessToken(
        token=token, client_id="release-qual-c5", scopes=["writeback:synthetic"]
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        async with Client(server) as client:
            response = await client.call_tool(
                "synthetic_writeback",
                {
                    "action": "apply",
                    "tenant_id": change.tenant_id,
                    "change_set_id": change.change_set_id,
                },
            )
    finally:
        auth_context_var.reset(reset)
    result = SyntheticWriteBackResult.model_validate(response.structured_content)
    assert result.receipt_id
    assert (await source.read_current(change)).source_version == "v1+1"
    page = await EpistemicGraphWriteBackLedger(restarted_eg, graph="graph:c5").receipts(
        change.tenant_id, change.change_set_id
    )
    assert len(page.receipts) == 1
    assert page.receipts[0].receipt.receipt_id == result.receipt_id


async def test_live_acceptance_runs_two_phases_against_granted_eg_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = _change_set()
    eg = _TenantEgClient(tmp_path / "eg", change.tenant_id)
    await EpistemicGraphWriteBackLedger(eg, graph="graph:c5").create(change)
    seed_synthetic_writeback_test_source(
        tmp_path / "source", change, initial_fields={"status": "new"}
    )
    with pytest.raises(WriteBackPersistenceError, match="already exists"):
        seed_synthetic_writeback_test_source(
            tmp_path / "source", change, initial_fields={"status": "new"}
        )
    token = "t" * 32
    monkeypatch.setenv(
        "C5_STATIC_TOKENS",
        json.dumps(
            {
                token: {
                    "client_id": "release-qual-c5",
                    "scopes": ["writeback:synthetic"],
                }
            }
        ),
    )
    options = [
        "--transport",
        "streamable-http",
        "--auth-type",
        "static",
        "--static-tokens-ref",
        "env://C5_STATIC_TOKENS",
    ]
    server, _ = build_synthetic_writeback_test_namespace_server(
        eg,
        tmp_path / "source",
        graph="graph:c5",
        tenant_id=change.tenant_id,
        client_id="release-qual-c5",
        command_args=options,
    )
    endpoint = TransportEndpoint(
        url="https://synthetic.example.invalid/mcp", bearer_token=token
    )
    kwargs = {
        "graph": "graph:c5",
        "tenant_id": change.tenant_id,
        "change_set_id": change.change_set_id,
        "expected_mode": WriteBackAuthorizationMode.PROPOSAL_APPROVAL,
    }
    with pytest.raises(ValueError, match="authenticated URL endpoint"):
        await run_live_synthetic_writeback_acceptance(
            eg,
            TransportEndpoint(url=endpoint.url),
            transport=_LiveFixtureTransport(server),
            **kwargs,
        )
    with pytest.raises(WriteBackPersistenceError, match="not granted"):
        await run_live_synthetic_writeback_acceptance(
            eg,
            endpoint,
            graph="graph:c5",
            tenant_id=change.tenant_id,
            change_set_id=change.change_set_id,
            expected_mode=WriteBackAuthorizationMode.STANDING_POLICY,
            transport=_LiveFixtureTransport(server),
        )
    access = AccessToken(
        token=token, client_id="release-qual-c5", scopes=["writeback:synthetic"]
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        first = await run_live_synthetic_writeback_acceptance(
            eg, endpoint, transport=_LiveFixtureTransport(server), **kwargs
        )
        assert (
            LiveSyntheticWriteBackEvidence.model_validate_json(first.model_dump_json())
            == first
        )
        restarted_eg = _TenantEgClient(tmp_path / "eg", change.tenant_id)
        restarted, _ = build_synthetic_writeback_test_namespace_server(
            restarted_eg,
            tmp_path / "source",
            graph="graph:c5",
            tenant_id=change.tenant_id,
            client_id="release-qual-c5",
            command_args=options,
        )
        second = await run_live_synthetic_writeback_acceptance(
            restarted_eg,
            endpoint,
            prior=first,
            transport=_LiveFixtureTransport(restarted),
            **kwargs,
        )
        assert first.server_instance_id != second.server_instance_id
        assert (
            second.model_copy(update={"server_instance_id": first.server_instance_id})
            == first
        )
        with pytest.raises(WriteBackPersistenceError, match="server instance"):
            await run_live_synthetic_writeback_acceptance(
                restarted_eg,
                endpoint,
                prior=second,
                transport=_LiveFixtureTransport(restarted),
                **kwargs,
            )
        with pytest.raises(WriteBackPersistenceError, match="restart evidence"):
            await run_live_synthetic_writeback_acceptance(
                restarted_eg,
                endpoint,
                prior=first.model_copy(update={"receipt_id": "wrong"}),
                transport=_LiveFixtureTransport(restarted),
                **kwargs,
            )
    finally:
        auth_context_var.reset(reset)
    assert (
        await FileWriteBackTransport(tmp_path / "source").read_current(change)
    ).source_version == "v1+1"
    await verify_synthetic_writeback_source_effect(tmp_path / "source", change, second)
    with pytest.raises(WriteBackPersistenceError, match="does not bind receipt"):
        await verify_synthetic_writeback_source_effect(
            tmp_path / "source",
            change,
            second.model_copy(update={"post_source_version": "wrong"}),
        )


async def test_test_namespace_serve_uses_network_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "t" * 32
    monkeypatch.setenv(
        "C5_STATIC_TOKENS",
        json.dumps(
            {token: {"client_id": "release-qual-c5", "scopes": ["writeback:synthetic"]}}
        ),
    )
    observed: dict[str, object] = {}

    async def record_run(self: Any, transport: str, **kwargs: object) -> None:
        observed.update({"transport": transport, **kwargs})

    monkeypatch.setattr("fastmcp.FastMCP.run_async", record_run)
    await serve_synthetic_writeback_test_namespace(
        object(),
        tmp_path / "source",
        graph="graph:c5",
        tenant_id="tenant-c5",
        client_id="release-qual-c5",
        command_args=[
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "8033",
            "--auth-type",
            "static",
            "--static-tokens-ref",
            "env://C5_STATIC_TOKENS",
        ],
    )
    assert observed["transport"] == "streamable-http"
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8033
    assert observed["middleware"]
