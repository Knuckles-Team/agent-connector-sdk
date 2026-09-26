"""Replay EG's append-only receipts into the write-back restart state."""

from __future__ import annotations

from enum import Enum, auto

from epistemic_graph.generated.write_back import (
    ReconciliationReceipt,
    SourceChangeSet,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
    WriteBackReceipt,
    WriteBackReceiptPage,
    WriteBackReceiptRecord,
    WriteBackReceiptRecordAttempt,
)

from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.writeback.errors import WriteBackPersistenceError

_RECEIPT_PAGE_LIMIT = 256


class _ReceiptRecoveryState(Enum):
    """The source-effect state reconstructed from durable receipts."""

    FRESH = auto()
    RETRYABLE = auto()
    UNCERTAIN = auto()
    APPLIED = auto()


_ATTEMPT_STATES = {
    (WriteBackOutcome.APPLIED, WriteBackEffectStatus.APPLIED): (
        _ReceiptRecoveryState.APPLIED
    ),
    (
        WriteBackOutcome.OUTCOME_UNCERTAIN,
        WriteBackEffectStatus.OUTCOME_UNCERTAIN,
    ): _ReceiptRecoveryState.UNCERTAIN,
}
_RECONCILIATION_STATES = {
    WriteBackEffectStatus.NO_EFFECT: _ReceiptRecoveryState.RETRYABLE,
    WriteBackEffectStatus.APPLIED: _ReceiptRecoveryState.APPLIED,
    WriteBackEffectStatus.OUTCOME_UNCERTAIN: _ReceiptRecoveryState.UNCERTAIN,
}


async def _receipt_recovery_state(
    ledger: WriteBackLedger, change_set: SourceChangeSet
) -> _ReceiptRecoveryState:
    """Read and validate the complete receipt stream in sequence order."""
    state = _ReceiptRecoveryState.FRESH
    after_sequence: int | None = None
    last_sequence = 0
    while True:
        page = await ledger.receipts(
            change_set.tenant_id,
            change_set.change_set_id,
            after_sequence=after_sequence,
            limit=_RECEIPT_PAGE_LIMIT,
        )
        state, last_sequence = _consume_page(
            change_set, page, state=state, last_sequence=last_sequence
        )
        if page.next_sequence is None:
            return state
        if after_sequence is not None and page.next_sequence <= after_sequence:
            raise WriteBackPersistenceError("EG receipt pagination did not advance")
        after_sequence = page.next_sequence


def _consume_page(
    change_set: SourceChangeSet,
    page: WriteBackReceiptPage,
    *,
    state: _ReceiptRecoveryState,
    last_sequence: int,
) -> tuple[_ReceiptRecoveryState, int]:
    for record in page.receipts:
        if record.receipt.sequence <= last_sequence:
            raise WriteBackPersistenceError(
                "EG receipt sequence is not strictly increasing"
            )
        last_sequence = record.receipt.sequence
        state = _advance_state(change_set, record, state)
    return state, last_sequence


def _advance_state(
    change_set: SourceChangeSet,
    record: WriteBackReceiptRecord,
    state: _ReceiptRecoveryState,
) -> _ReceiptRecoveryState:
    next_state = _record_state(change_set, record)
    is_attempt = isinstance(record, WriteBackReceiptRecordAttempt)
    if state in (_ReceiptRecoveryState.FRESH, _ReceiptRecoveryState.RETRYABLE):
        if not is_attempt:
            raise WriteBackPersistenceError(
                "durable reconciliation has no uncertain attempt"
            )
    elif is_attempt:
        raise WriteBackPersistenceError(
            "durable attempt has no proven retry permission"
        )
    elif state is _ReceiptRecoveryState.APPLIED:
        raise WriteBackPersistenceError(
            "durable applied effect cannot be reconciled again"
        )
    return next_state


def _record_state(
    change_set: SourceChangeSet, record: WriteBackReceiptRecord
) -> _ReceiptRecoveryState:
    if isinstance(record, WriteBackReceiptRecordAttempt):
        _require_attempt_receipt(change_set, record.receipt)
        return _ATTEMPT_STATES[(record.receipt.outcome, record.receipt.effect_status)]
    receipt = record.receipt
    _require_reconciliation_receipt(change_set, receipt)
    return _RECONCILIATION_STATES[receipt.effect_status]


def _require_attempt_receipt(
    change_set: SourceChangeSet, receipt: WriteBackReceipt
) -> None:
    _require_receipt_identity(
        change_set,
        (
            receipt.tenant_id,
            receipt.change_set_id,
            receipt.change_set_digest,
            receipt.idempotency_key,
        ),
    )
    _require_receipt_principal(change_set, receipt.actor, receipt.schema_version)
    binding_matches = (
        receipt.authorization == change_set.authorization
        and receipt.policy_digest == change_set.policy_digest
        and receipt.input_digest == change_set.authorization.input_digest
        and receipt.output_digest == change_set.authorization.output_digest
        and receipt.applied_field_digest == change_set.patch_digest()
        and receipt.kind is WriteBackAttemptKind.APPLY
    )
    if (
        not binding_matches
        or (
            receipt.outcome,
            receipt.effect_status,
        )
        not in _ATTEMPT_STATES
    ):
        raise WriteBackPersistenceError("durable attempt receipt binding mismatch")


def _require_reconciliation_receipt(
    change_set: SourceChangeSet, receipt: ReconciliationReceipt
) -> None:
    _require_receipt_identity(
        change_set,
        (
            receipt.tenant_id,
            receipt.change_set_id,
            receipt.change_set_digest,
            receipt.idempotency_key,
        ),
    )
    _require_receipt_principal(change_set, receipt.actor, receipt.schema_version)
    retry_forbidden = receipt.effect_status in (
        WriteBackEffectStatus.APPLIED,
        WriteBackEffectStatus.OUTCOME_UNCERTAIN,
    )
    binding_matches = (
        receipt.authorization == change_set.authorization
        and receipt.policy_digest == change_set.policy_digest
        and (not retry_forbidden or not receipt.retry_allowed)
        and (
            receipt.effect_status is not WriteBackEffectStatus.NO_EFFECT
            or receipt.retry_allowed
        )
    )
    if not binding_matches:
        raise WriteBackPersistenceError(
            "durable reconciliation receipt binding mismatch"
        )


def _require_receipt_identity(
    change_set: SourceChangeSet,
    observed: tuple[str, str, str, str],
) -> None:
    expected = (
        change_set.tenant_id,
        change_set.change_set_id,
        change_set.change_set_digest,
        change_set.idempotency_key,
    )
    if observed != expected:
        raise WriteBackPersistenceError("durable receipt identity mismatch")


def _require_receipt_principal(
    change_set: SourceChangeSet, actor: str, schema_version: int
) -> None:
    if actor != change_set.actor or schema_version != change_set.schema_version:
        raise WriteBackPersistenceError("durable receipt principal mismatch")
