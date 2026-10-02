"""EH-216: a writable reference connector survives a real OS process kill.

``tests/test_writeback_durable.py`` proves restart-safety by discarding a
Python object and building a fresh one in the *same* process; the durable
state it depends on (``MemoryLedger``) is a plain in-memory fixture kept
alive only because the test never actually leaves that process. This test
proves the same D18 contract (RF-ADR-009 Section 2.2.2: "no retry decision is
held only in memory") across a genuine process boundary: a child process
mutates the reference source, is killed with ``SIGKILL`` before it can record
the durable attempt receipt, and a brand new process -- sharing no Python
object, heap, or asyncio state with the one that died -- completes the
attempt correctly by reading only the two files
``DurableWritableConnector`` and ``FileWriteBackTransport`` depend on.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import signal
import time
from pathlib import Path

from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAuthorizationDecision,
    WriteBackAuthorizationMode,
    WriteBackEffectStatus,
)

from agent_connector_sdk.writeback.audit import InMemoryAuditReservation
from agent_connector_sdk.writeback.connector import DurableWritableConnector
from agent_connector_sdk.writeback.durable_ledger import FileWriteBackLedger
from agent_connector_sdk.writeback.durable_transport import FileWriteBackTransport


def _reference_change_set() -> SourceChangeSet:
    authorization = WriteBackAuthorizationDecision(
        mode=WriteBackAuthorizationMode.STANDING_POLICY,
        authorization_ref="policy:ticket-status",
        decision_digest="2" * 64,
        input_digest="3" * 64,
        output_digest="4" * 64,
        authorized=True,
    )
    change = SourceChangeSet(
        schema_version=1,
        change_set_id="change-restart-1",
        change_set_digest="0" * 64,
        tenant_id="tenant-restart",
        actor="principal:reference-connector",
        purpose="restart-proof reference write-back",
        connector_id="reference-connector",
        source_instance_id="reference-source",
        entity_id="ticket-restart-1",
        base_source_version="v1",
        desired_patch={"status": "approved"},
        field_scope=["status"],
        source_of_truth_rule="source_accepts_approved_status",
        field_provenance={"status": "fixture:status"},
        required_capability="ticket.write",
        policy_digest="1" * 64,
        authorization=authorization,
        idempotency_key="write:restart-1",
        expires_at_ms=time.time_ns() // 1_000_000 + 3_600_000,
        reconciliation_procedure="lookup by idempotency key then read ticket",
    )
    return change.model_copy(update={"change_set_digest": change.canonical_digest()})


class _KillAfterApplyTransport(FileWriteBackTransport):
    """Die the instant the durable source is mutated, before any receipt.

    This reproduces the exact hazard D18 write-back exists to survive: the
    real system was already changed, but nothing durable yet records that an
    attempt happened.
    """

    async def apply(self, change_set: SourceChangeSet, expected_version: str) -> object:
        attempt = await super().apply(change_set, expected_version)
        os.kill(os.getpid(), signal.SIGKILL)
        return attempt  # pragma: no cover - unreachable, the process is dead


async def _register_and_apply_until_killed(
    directory: str, change_set_payload: dict[str, object]
) -> None:
    change_set = SourceChangeSet.model_validate(change_set_payload)
    root = Path(directory)
    ledger = FileWriteBackLedger(root / "ledger")
    transport = _KillAfterApplyTransport(root / "transport")
    connector = DurableWritableConnector(
        change_set.connector_id, transport, ledger, audit=InMemoryAuditReservation()
    )
    await connector.register(change_set)
    await connector.apply(change_set)  # never returns: SIGKILL fires inside apply()


def _run_child(directory: str, change_set_payload: dict[str, object]) -> None:
    asyncio.run(_register_and_apply_until_killed(directory, change_set_payload))


def test_writable_connector_survives_a_kill_mid_attempt(tmp_path: Path) -> None:
    change_set = _reference_change_set()
    seed_transport = FileWriteBackTransport(tmp_path / "transport")
    seed_transport.seed(change_set.entity_id, "v1", {"status": "new"})

    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_run_child,
        args=(str(tmp_path), change_set.model_dump(mode="json")),
    )
    child.start()
    child.join(timeout=60)

    assert child.exitcode == -signal.SIGKILL, (
        "the child must die by SIGKILL inside apply(), not exit cleanly"
    )

    restarted_ledger = FileWriteBackLedger(tmp_path / "ledger")
    restarted_transport = FileWriteBackTransport(tmp_path / "transport")
    restarted = DurableWritableConnector(
        change_set.connector_id,
        restarted_transport,
        restarted_ledger,
        audit=InMemoryAuditReservation(),
    )

    async def _after_restart() -> None:
        applied = await restarted.apply(change_set)
        assert applied.effect_status is WriteBackEffectStatus.APPLIED
        assert applied.post_source_version == "v1+1"

        page = await restarted_ledger.receipts(
            change_set.tenant_id, change_set.change_set_id
        )
        assert len(page.receipts) == 1, (
            "the restarted process must durably record the receipt the "
            "killed process never reached"
        )

        again = await restarted.apply(change_set)
        assert again == applied, "a second apply must not re-mutate the source"

    asyncio.run(_after_restart())
