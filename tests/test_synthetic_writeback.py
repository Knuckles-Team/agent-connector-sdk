"""C5 synthetic source: served action contract and durable replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
)
from fastmcp import Client

from agent_connector_sdk.certify.listing import list_server_tools
from agent_connector_sdk.manifest.loader import load_manifest
from agent_connector_sdk.manifest.tool_schema import (
    canonical_input_schema,
    canonical_output_schema,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.testing.synthetic_writeback import (
    SyntheticWriteBackResult,
    build_synthetic_writeback_eg_server,
    build_synthetic_writeback_server,
)
from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.transports.mcp import McpTransport
from agent_connector_sdk.writeback.durable_ledger import FileWriteBackLedger
from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport
from agent_connector_sdk.writeback.epistemic_graph import EpistemicGraphWriteBackLedger

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


def _digest(schema: dict[str, object] | None) -> str:
    body = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


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
    assert action.input_schema_sha256 == _digest(input_schema)
    assert action.output_schema_sha256 == _digest(output_schema)


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
        assert second == first
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
    assert first == second and first.receipt_id
    assert (await source.read_current(change)).source_version == "v1+1"
    page = await EpistemicGraphWriteBackLedger(restarted_eg, graph="graph:c5").receipts(
        change.tenant_id, change.change_set_id
    )
    assert len(page.receipts) == 1
    assert page.receipts[0].receipt.receipt_id == first.receipt_id
    assert eg.methods and restarted_eg.methods
