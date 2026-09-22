"""A durable, file-backed reference ``WriteBackLedger`` for restart proofs.

Every correctness property this SDK claims for D18 write-back (RF-ADR-009
SS2.2.2: "no retry decision is held only in memory") only means something if
the ledger it is checked against survives the death of the SDK process that
wrote to it. :class:`~agent_connector_sdk.writeback.epistemic_graph.
EpistemicGraphWriteBackLedger` is the production implementation, durable in
EG; this reference implementation is durable on the local filesystem
instead, so a process-kill integration test can prove the same restart
contract without a live EG connection -- the same relationship
:class:`~agent_connector_sdk.writeback.memory.InMemoryWriteBackTransport` has
to a real connector's HTTP transport, made durable instead of in-memory.
"""

from __future__ import annotations

from pathlib import Path

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    ReconciliationReceipt,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackReceipt,
    WriteBackReceiptPage,
    WriteBackReceiptRecord,
    WriteBackReceiptRecordAttempt,
    WriteBackReceiptRecordReconciliation,
)
from pydantic import TypeAdapter

from agent_connector_sdk.writeback.durable_files import read_json, write_json_atomic
from agent_connector_sdk.writeback.errors import WriteBackPersistenceError

__all__ = ["FileWriteBackLedger"]

_RECORD_ADAPTER: TypeAdapter[WriteBackReceiptRecord] = TypeAdapter(
    WriteBackReceiptRecord
)


class FileWriteBackLedger:
    """Persist one durable change set and its append-only receipts as JSON."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._change_set_path = directory / "change_set.json"
        self._receipts_path = directory / "receipts.json"

    async def create(self, change_set: SourceChangeSet) -> SourceChangeSet:
        """Create or idempotently recover one canonical change set."""
        existing = self._read_change_set()
        if existing is not None and existing != change_set:
            raise WriteBackPersistenceError("change-set identity conflict")
        if existing is None:
            write_json_atomic(self._change_set_path, change_set.model_dump(mode="json"))
        return change_set

    async def get(self, tenant_id: str, change_set_id: str) -> SourceChangeSet | None:
        """Read the durable canonical change set."""
        change_set = self._read_change_set()
        if change_set is None:
            return None
        identity = (change_set.tenant_id, change_set.change_set_id)
        if identity != (tenant_id, change_set_id):
            return None
        return change_set

    async def record_attempt(self, attempt: WriteBackAttempt) -> WriteBackReceipt:
        """Append one source-effect attempt receipt."""
        change_set = self._existing_change_set()
        records = self._read_receipts()
        receipt = WriteBackReceipt(
            **attempt.model_dump(),
            actor=change_set.actor,
            authorization=change_set.authorization,
            policy_digest=change_set.policy_digest,
            receipt_id=f"attempt:{len(records) + 1}",
            recorded_at_ms=0,
            schema_version=change_set.schema_version,
            sequence=len(records) + 1,
        )
        record = WriteBackReceiptRecordAttempt(receipt_kind="attempt", receipt=receipt)
        self._write_receipts([*records, record])
        return receipt

    async def record_reconciliation(
        self, observation: ReconciliationObservation
    ) -> ReconciliationReceipt:
        """Append one reconciliation receipt."""
        change_set = self._existing_change_set()
        records = self._read_receipts()
        receipt = ReconciliationReceipt(
            **observation.model_dump(),
            actor=change_set.actor,
            authorization=change_set.authorization,
            policy_digest=change_set.policy_digest,
            receipt_id=f"reconciliation:{len(records) + 1}",
            recorded_at_ms=0,
            schema_version=change_set.schema_version,
            sequence=len(records) + 1,
        )
        record = WriteBackReceiptRecordReconciliation(
            receipt_kind="reconciliation", receipt=receipt
        )
        self._write_receipts([*records, record])
        return receipt

    async def receipts(
        self,
        tenant_id: str,
        change_set_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 256,
    ) -> WriteBackReceiptPage:
        """Read an ordered page of append-only receipts."""
        self._existing_change_set()
        after = after_sequence or 0
        remaining = [
            record
            for record in self._read_receipts()
            if record.receipt.sequence > after
        ]
        selected = remaining[:limit]
        next_sequence = (
            selected[-1].receipt.sequence if len(remaining) > limit else None
        )
        return WriteBackReceiptPage(receipts=selected, next_sequence=next_sequence)

    def _read_change_set(self) -> SourceChangeSet | None:
        payload = read_json(self._change_set_path)
        return None if payload is None else SourceChangeSet.model_validate(payload)

    def _existing_change_set(self) -> SourceChangeSet:
        change_set = self._read_change_set()
        if change_set is None:
            raise WriteBackPersistenceError("no durable change set is registered")
        return change_set

    def _read_receipts(self) -> list[WriteBackReceiptRecord]:
        payload = read_json(self._receipts_path) or []
        return [_RECORD_ADAPTER.validate_python(item) for item in payload]

    def _write_receipts(self, records: list[WriteBackReceiptRecord]) -> None:
        write_json_atomic(
            self._receipts_path,
            [record.model_dump(mode="json") for record in records],
        )
