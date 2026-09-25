"""Generated-client adapter for EG's durable ``WriteBack`` authority."""

from __future__ import annotations

from typing import Any

from epistemic_graph.generated.storage import send_write_back
from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    ReconciliationReceipt,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackOpCreate,
    WriteBackOpGet,
    WriteBackOpReceipts,
    WriteBackOpRecordAttempt,
    WriteBackOpRecordReconciliation,
    WriteBackReceipt,
    WriteBackReceiptPage,
)
from pydantic import BaseModel, ValidationError

from agent_connector_sdk.writeback.errors import WriteBackPersistenceError

__all__ = ["EpistemicGraphWriteBackLedger"]


class EpistemicGraphWriteBackLedger:
    """Use only generated EG operations and DTOs for durable write-back state."""

    def __init__(self, client: Any, *, graph: str | None = None) -> None:
        self._client = client
        self._graph = graph

    async def create(self, change_set: SourceChangeSet) -> SourceChangeSet:
        """Create one change set under its canonical idempotency key."""
        created = await self._send(
            WriteBackOpCreate(op="create", change_set=change_set),
            SourceChangeSet,
            idempotency_key=change_set.idempotency_key,
        )
        if created != change_set:
            raise WriteBackPersistenceError("EG created a different change set")
        return created

    async def get(self, tenant_id: str, change_set_id: str) -> SourceChangeSet | None:
        """Read one change set, returning ``None`` only when EG does."""
        operation = WriteBackOpGet(
            op="get", tenant_id=tenant_id, change_set_id=change_set_id
        )
        payload = await self._payload(operation)
        if payload is None:
            return None
        change_set = self._validate(SourceChangeSet, payload)
        if (change_set.tenant_id, change_set.change_set_id) != (
            tenant_id,
            change_set_id,
        ):
            raise WriteBackPersistenceError("EG returned another change set")
        return change_set

    async def record_attempt(self, attempt: WriteBackAttempt) -> WriteBackReceipt:
        """Append one exact source-effect attempt."""
        receipt = await self._send(
            WriteBackOpRecordAttempt(op="record_attempt", attempt=attempt),
            WriteBackReceipt,
            idempotency_key=attempt.idempotency_key,
        )
        self._require_echo(attempt, receipt)
        return receipt

    async def record_reconciliation(
        self, observation: ReconciliationObservation
    ) -> ReconciliationReceipt:
        """Append one exact reconciliation observation."""
        receipt = await self._send(
            WriteBackOpRecordReconciliation(
                op="record_reconciliation", observation=observation
            ),
            ReconciliationReceipt,
            idempotency_key=observation.idempotency_key,
        )
        self._require_echo(observation, receipt)
        return receipt

    async def receipts(
        self,
        tenant_id: str,
        change_set_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 256,
    ) -> WriteBackReceiptPage:
        """Read one typed receipt page."""
        page = await self._send(
            WriteBackOpReceipts(
                op="receipts",
                tenant_id=tenant_id,
                change_set_id=change_set_id,
                after_sequence=after_sequence,
                limit=limit,
            ),
            WriteBackReceiptPage,
        )
        previous = after_sequence or 0
        for record in page.receipts:
            receipt = record.receipt
            if (
                receipt.tenant_id != tenant_id
                or receipt.change_set_id != change_set_id
                or receipt.sequence <= previous
            ):
                raise WriteBackPersistenceError("EG receipt page binding mismatch")
            previous = receipt.sequence
        if (
            len(page.receipts) > limit
            or (page.next_sequence is not None and page.next_sequence != previous)
            or (page.next_sequence is not None and not page.receipts)
        ):
            raise WriteBackPersistenceError("EG receipt pagination is invalid")
        return page

    @staticmethod
    def _require_echo(source: BaseModel, receipt: BaseModel) -> None:
        fields = type(source).model_fields.keys()
        if any(getattr(source, name) != getattr(receipt, name) for name in fields):
            raise WriteBackPersistenceError("EG returned a different write-back receipt")

    async def _send[ModelT: BaseModel](
        self,
        operation: BaseModel,
        model: type[ModelT],
        *,
        idempotency_key: str | None = None,
    ) -> ModelT:
        payload = await self._payload(operation, idempotency_key=idempotency_key)
        return self._validate(model, payload)

    async def _payload(
        self, operation: BaseModel, *, idempotency_key: str | None = None
    ) -> Any:
        result = await send_write_back(
            self._client,
            {"op": operation.model_dump(mode="json", exclude_none=True)},
            self._graph,
            idempotency_key=idempotency_key,
        )
        return result.payload

    @staticmethod
    def _validate[ModelT: BaseModel](model: type[ModelT], payload: Any) -> ModelT:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise WriteBackPersistenceError(
                f"EG returned an invalid {model.__name__} write-back body"
            ) from exc
