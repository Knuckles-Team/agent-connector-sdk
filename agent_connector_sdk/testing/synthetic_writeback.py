"""Synthetic D18 source for a tenant-scoped served write-back proof."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    WriteBackAttempt,
)
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, JsonValue

from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.writeback.connector import DurableWritableConnector
from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport
from agent_connector_sdk.writeback.epistemic_graph import EpistemicGraphWriteBackLedger
from agent_connector_sdk.writeback.errors import WriteBackPersistenceError
from agent_connector_sdk.writeback.models import DryRunObservation

__all__ = [
    "SyntheticWriteBackResult",
    "build_synthetic_writeback_eg_server",
    "build_synthetic_writeback_server",
]

CONNECTOR_ID = "synthetic-writeback"
SOURCE_INSTANCE_ID = "synthetic-source"
CAPABILITY = "ticket.write"


class SyntheticWriteBackResult(BaseModel):
    """Source observation and EG receipt identity returned by the synthetic tool."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["dry_run", "apply", "reconcile"]
    observation: dict[str, JsonValue]
    receipt_id: str | None


async def _latest_receipt_id(
    ledger: WriteBackLedger, tenant_id: str, change_set_id: str
) -> str:
    after_sequence: int | None = None
    receipt_id = ""
    while True:
        page = await ledger.receipts(
            tenant_id, change_set_id, after_sequence=after_sequence, limit=256
        )
        if page.receipts:
            receipt_id = page.receipts[-1].receipt.receipt_id
        if page.next_sequence is None:
            break
        if after_sequence is not None and page.next_sequence <= after_sequence:
            raise WriteBackPersistenceError("EG receipt pagination did not advance")
        after_sequence = page.next_sequence
    if not receipt_id:
        raise WriteBackPersistenceError("EG did not persist a write-back receipt")
    return receipt_id


def build_synthetic_writeback_server(
    ledger: WriteBackLedger, source_dir: Path, *, tenant_id: str
) -> FastMCP[Any]:
    """Serve only pre-existing EG change sets for one test tenant.

    The caller seeds ``FileWriteBackTransport`` with a synthetic ticket. The
    tool never creates an approval or accepts a caller-supplied change set.
    ``ledger`` can be EG's generated-client adapter in a test namespace.
    """
    if not tenant_id:
        raise ValueError("tenant_id must not be empty")
    expected_tenant = tenant_id
    transport = FileWriteBackTransport(source_dir)
    connector = DurableWritableConnector(CONNECTOR_ID, transport, ledger)
    mcp: FastMCP[Any] = FastMCP(CONNECTOR_ID, version="1.0.0")

    @mcp.tool()
    async def synthetic_writeback(
        action: Literal["dry_run", "apply", "reconcile"],
        tenant_id: str,
        change_set_id: str,
    ) -> SyntheticWriteBackResult:
        """Preview, apply or reconcile a pre-authorized synthetic ticket change."""
        if tenant_id != expected_tenant:
            raise WriteBackPersistenceError("synthetic tenant is not granted")
        change_set = await ledger.get(tenant_id, change_set_id)
        if change_set is None:
            raise WriteBackPersistenceError("EG change set does not exist")
        if (
            change_set.connector_id != CONNECTOR_ID
            or change_set.source_instance_id != SOURCE_INSTANCE_ID
            or change_set.required_capability != CAPABILITY
            or change_set.field_scope != ["status"]
        ):
            raise WriteBackPersistenceError("synthetic source scope mismatch")
        observation: DryRunObservation | WriteBackAttempt | ReconciliationObservation
        if action == "dry_run":
            observation = await connector.dry_run(change_set)
            receipt_id = None
        elif action == "apply":
            observation = await connector.apply(change_set)
            receipt_id = await _latest_receipt_id(ledger, tenant_id, change_set_id)
        else:
            observation = await connector.reconcile(change_set)
            receipt_id = await _latest_receipt_id(ledger, tenant_id, change_set_id)
        return SyntheticWriteBackResult(
            action=action,
            observation=observation.model_dump(mode="json"),
            receipt_id=receipt_id,
        )

    return mcp


def build_synthetic_writeback_eg_server(
    eg_client: Any,
    source_dir: Path,
    *,
    graph: str,
    tenant_id: str,
) -> FastMCP[Any]:
    """Bind the test source to EG's generated durable WriteBack operations.

    ``eg_client`` must already carry a tenant-granted verified context. EG
    authorizes every create, read and receipt append; the SDK never mints a
    principal or stores a credential in this fixture.
    """
    if not graph:
        raise ValueError("graph must not be empty")
    return build_synthetic_writeback_server(
        EpistemicGraphWriteBackLedger(eg_client, graph=graph),
        source_dir,
        tenant_id=tenant_id,
    )
