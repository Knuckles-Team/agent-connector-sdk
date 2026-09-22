"""Durable EG-backed D18 write-back composition and restart recovery."""

from __future__ import annotations

from typing import Any

import pytest
from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    ReconciliationReceipt,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackEffectStatus,
    WriteBackReceipt,
    WriteBackReceiptPage,
    WriteBackReceiptRecord,
    WriteBackReceiptRecordAttempt,
    WriteBackReceiptRecordReconciliation,
)

from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.testing.writeback import make_writeback_fixture
from agent_connector_sdk.writeback.authorization import DurableAuthorizationResolver
from agent_connector_sdk.writeback.connector import DurableWritableConnector
from agent_connector_sdk.writeback.epistemic_graph import (
    EpistemicGraphWriteBackLedger,
)
from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    ReconciliationRequiredError,
    WriteBackPersistenceError,
)
from agent_connector_sdk.writeback.memory import FixtureUncertainty


class MemoryLedger:
    def __init__(self) -> None:
        self.change_set: SourceChangeSet | None = None
        self.records: list[WriteBackReceiptRecord] = []

    async def create(self, change_set: SourceChangeSet) -> SourceChangeSet:
        if self.change_set is not None and self.change_set != change_set:
            raise WriteBackPersistenceError("change-set identity conflict")
        self.change_set = change_set
        return change_set

    async def get(self, tenant_id: str, change_set_id: str) -> SourceChangeSet | None:
        change_set = self.change_set
        if change_set is None:
            return None
        if (tenant_id, change_set_id) != (
            change_set.tenant_id,
            change_set.change_set_id,
        ):
            return None
        return change_set

    async def record_attempt(self, attempt: WriteBackAttempt) -> WriteBackReceipt:
        change_set = self._change_set()
        receipt = WriteBackReceipt(
            **attempt.model_dump(),
            actor=change_set.actor,
            authorization=change_set.authorization,
            policy_digest=change_set.policy_digest,
            receipt_id=f"attempt:{len(self.records) + 1}",
            recorded_at_ms=1,
            schema_version=change_set.schema_version,
            sequence=len(self.records) + 1,
        )
        self.records.append(
            WriteBackReceiptRecordAttempt(receipt_kind="attempt", receipt=receipt)
        )
        return receipt

    async def record_reconciliation(
        self, observation: ReconciliationObservation
    ) -> ReconciliationReceipt:
        change_set = self._change_set()
        receipt = ReconciliationReceipt(
            **observation.model_dump(),
            actor=change_set.actor,
            authorization=change_set.authorization,
            policy_digest=change_set.policy_digest,
            receipt_id=f"reconciliation:{len(self.records) + 1}",
            recorded_at_ms=1,
            schema_version=change_set.schema_version,
            sequence=len(self.records) + 1,
        )
        self.records.append(
            WriteBackReceiptRecordReconciliation(
                receipt_kind="reconciliation", receipt=receipt
            )
        )
        return receipt

    async def receipts(
        self,
        tenant_id: str,
        change_set_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 256,
    ) -> WriteBackReceiptPage:
        self._change_set()
        after = after_sequence or 0
        remaining = [
            record for record in self.records if record.receipt.sequence > after
        ]
        selected = remaining[:limit]
        next_sequence = (
            selected[-1].receipt.sequence if len(remaining) > limit else None
        )
        return WriteBackReceiptPage(receipts=selected, next_sequence=next_sequence)

    def _change_set(self) -> SourceChangeSet:
        if self.change_set is None:
            raise WriteBackPersistenceError("missing fixture change set")
        return self.change_set


class RecordingEgClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any], str | None, str | None]] = []

    async def _send(
        self,
        method: str,
        params: dict[str, Any],
        graph: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> Any:
        self.calls.append((method, params, graph, idempotency_key))
        return self.responses.pop(0)


async def test_generated_eg_adapter_uses_typed_ops_and_idempotency_keys() -> None:
    fixture = make_writeback_fixture()
    memory = MemoryLedger()
    change_set = await memory.create(fixture.change_set)
    attempt = await fixture.port.apply(change_set)
    attempt_receipt = await memory.record_attempt(attempt)
    observation = await fixture.transport.reconcile(change_set)
    reconciliation_receipt = await memory.record_reconciliation(observation)
    page = await memory.receipts(change_set.tenant_id, change_set.change_set_id)
    client = RecordingEgClient(
        [
            change_set.model_dump(mode="json"),
            change_set.model_dump(mode="json"),
            attempt_receipt.model_dump(mode="json"),
            reconciliation_receipt.model_dump(mode="json"),
            page.model_dump(mode="json"),
        ]
    )
    ledger = EpistemicGraphWriteBackLedger(client, graph="graph:fixture")

    assert await ledger.create(change_set) == change_set
    assert (
        await ledger.get(change_set.tenant_id, change_set.change_set_id) == change_set
    )
    assert await ledger.record_attempt(attempt) == attempt_receipt
    assert await ledger.record_reconciliation(observation) == reconciliation_receipt
    assert await ledger.receipts(change_set.tenant_id, change_set.change_set_id) == page
    assert [call[1]["op"]["op"] for call in client.calls] == [
        "create",
        "get",
        "record_attempt",
        "record_reconciliation",
        "receipts",
    ]
    assert client.calls[0][3] == change_set.idempotency_key
    assert client.calls[2][3] == change_set.idempotency_key
    assert client.calls[3][3] == change_set.idempotency_key


async def test_uncertain_effect_is_reconciled_after_process_restart() -> None:
    fixture = make_writeback_fixture()
    ledger = MemoryLedger()
    connector = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    await connector.register(fixture.change_set)
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.AFTER_EFFECT
    )

    uncertain = await connector.apply(fixture.change_set)
    assert uncertain.effect_status is WriteBackEffectStatus.OUTCOME_UNCERTAIN

    restarted = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    with pytest.raises(ReconciliationRequiredError):
        await restarted.apply(fixture.change_set)
    reconciled = await restarted.reconcile(fixture.change_set)
    assert reconciled.effect_status is WriteBackEffectStatus.APPLIED

    restarted_again = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    applied = await restarted_again.apply(fixture.change_set)
    assert applied.effect_status is WriteBackEffectStatus.APPLIED
    assert fixture.transport.attempts == 1


async def test_proven_no_effect_allows_one_restart_retry() -> None:
    fixture = make_writeback_fixture()
    ledger = MemoryLedger()
    connector = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    await connector.register(fixture.change_set)
    fixture.transport.inject_uncertainty(
        fixture.change_set.idempotency_key, FixtureUncertainty.BEFORE_EFFECT
    )
    await connector.apply(fixture.change_set)

    restarted = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    reconciled = await restarted.reconcile(fixture.change_set)
    assert reconciled.effect_status is WriteBackEffectStatus.NO_EFFECT

    restarted_again = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    applied = await restarted_again.apply(fixture.change_set)
    assert applied.effect_status is WriteBackEffectStatus.APPLIED
    assert fixture.transport.attempts == 2


async def test_durable_authorization_resolver_fails_closed() -> None:
    fixture = make_writeback_fixture()
    ledger = MemoryLedger()
    resolver = DurableAuthorizationResolver(ledger)
    assert isinstance(ledger, WriteBackLedger)

    with pytest.raises(AuthorizationDeniedError, match="does not exist"):
        await resolver.verify(fixture.change_set)

    denied_authorization = fixture.change_set.authorization.model_copy(
        update={"authorized": False}
    )
    denied = fixture.change_set.model_copy(
        update={
            "authorization": denied_authorization,
            "change_set_digest": "0" * 64,
        }
    )
    denied = denied.model_copy(update={"change_set_digest": denied.canonical_digest()})
    await ledger.create(denied)
    with pytest.raises(AuthorizationDeniedError, match="authorization denied"):
        await resolver.verify(denied)


async def test_writable_connector_rejects_noncanonical_or_wrong_connector() -> None:
    fixture = make_writeback_fixture()
    ledger = MemoryLedger()
    connector = DurableWritableConnector(
        fixture.change_set.connector_id, fixture.transport, ledger
    )
    with pytest.raises(WriteBackPersistenceError, match="does not exist"):
        await connector.apply(fixture.change_set)

    wrong_connector = fixture.change_set.model_copy(update={"connector_id": "other"})
    with pytest.raises(ValueError, match="another connector"):
        await connector.register(wrong_connector)
