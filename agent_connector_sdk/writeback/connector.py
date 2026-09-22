"""Durable writable-connector composition for the D18 protocol."""

from __future__ import annotations

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
)

from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.ports.writeback_transport import WriteBackTransport
from agent_connector_sdk.writeback.authorization import DurableAuthorizationResolver
from agent_connector_sdk.writeback.errors import (
    ChangeSetValidationError,
    ReconciliationRequiredError,
    WriteBackPersistenceError,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot
from agent_connector_sdk.writeback.recovery import (
    _receipt_recovery_state,
    _ReceiptRecoveryState,
)
from agent_connector_sdk.writeback.service import GovernedWriteBack
from agent_connector_sdk.writeback.validation import require_effect

__all__ = ["DurableWritableConnector"]


class DurableWritableConnector:
    """Bind one writable connector to EG's canonical records and receipts.

    No retry decision is held only in memory. Before every apply the complete
    append-only receipt stream is replayed, so a replacement process refuses an
    unresolved effect and permits retry only after a durable ``NO_EFFECT``
    reconciliation receipt.
    """

    def __init__(
        self,
        connector_id: str,
        transport: WriteBackTransport,
        ledger: WriteBackLedger,
    ) -> None:
        if not connector_id:
            raise ValueError("connector_id must not be empty")
        self._connector_id = connector_id
        self._transport = transport
        self._ledger = ledger
        self._governed = GovernedWriteBack(
            transport, DurableAuthorizationResolver(ledger)
        )

    async def register(self, change_set: SourceChangeSet) -> SourceChangeSet:
        """Persist the canonical request before any source-side operation."""
        self._require_connector(change_set)
        created = await self._ledger.create(change_set)
        if created != change_set:
            raise WriteBackPersistenceError("EG created a different change set")
        return created

    async def current_version(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read source state for an exact durable change set."""
        durable = await self._authoritative(change_set)
        return await self._governed.current_version(durable)

    async def dry_run(self, change_set: SourceChangeSet) -> DryRunObservation:
        """Preview an exact durable change set without recording an effect."""
        durable = await self._authoritative(change_set)
        return await self._governed.dry_run(durable)

    async def apply(self, change_set: SourceChangeSet) -> WriteBackAttempt:
        """Apply once and append the attempt before returning to the caller."""
        durable = await self._authoritative(change_set)
        state = await _receipt_recovery_state(self._ledger, durable)
        if state is _ReceiptRecoveryState.UNCERTAIN:
            raise ReconciliationRequiredError(
                "durable uncertain outcome must reconcile before retry"
            )
        if state is _ReceiptRecoveryState.APPLIED:
            prior = await self._transport.prior_effect(durable)
            if prior is None:
                raise WriteBackPersistenceError(
                    "durable applied receipt has no matching source effect"
                )
            require_effect(durable, prior)
            return prior

        attempt = await self._governed.apply(durable)
        await self._ledger.record_attempt(attempt)
        return attempt

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Reconcile a durable uncertain attempt and append the observation."""
        durable = await self._authoritative(change_set)
        state = await _receipt_recovery_state(self._ledger, durable)
        if state is not _ReceiptRecoveryState.UNCERTAIN:
            raise ReconciliationRequiredError(
                "no durable uncertain outcome requires reconciliation"
            )
        observation = await self._governed.reconcile(durable)
        await self._ledger.record_reconciliation(observation)
        return observation

    async def _authoritative(self, change_set: SourceChangeSet) -> SourceChangeSet:
        self._require_connector(change_set)
        durable = await self._ledger.get(change_set.tenant_id, change_set.change_set_id)
        if durable is None:
            raise WriteBackPersistenceError("durable change set does not exist")
        if (
            durable != change_set
            or durable.change_set_digest != durable.canonical_digest()
        ):
            raise WriteBackPersistenceError("durable change-set binding mismatch")
        return durable

    def _require_connector(self, change_set: SourceChangeSet) -> None:
        if change_set.connector_id != self._connector_id:
            raise ChangeSetValidationError("change set targets another connector")
