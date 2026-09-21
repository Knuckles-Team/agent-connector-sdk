"""Governed implementation of the D18 write-back protocol."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
)

from agent_connector_sdk.ports.authorization_verifier import AuthorizationVerifier
from agent_connector_sdk.ports.writeback_transport import WriteBackTransport
from agent_connector_sdk.writeback.errors import (
    ChangeSetExpiredError,
    ChangeSetValidationError,
    OutcomeUncertainError,
    ReconciliationRequiredError,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot
from agent_connector_sdk.writeback.validation import (
    require_authorized,
    require_base,
    require_effect,
    require_reconciliation,
)

__all__ = ["GovernedWriteBack"]


class GovernedWriteBack:
    """Checks canonical scope, version, expiry and authorization before mutation."""

    def __init__(
        self,
        transport: WriteBackTransport,
        verifier: AuthorizationVerifier,
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._transport = transport
        self._verifier = verifier
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._unresolved: dict[str, str] = {}

    async def current_version(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read current source state after validating the EG contract."""
        self._validate(change_set)
        return await self._transport.read_current(change_set)

    async def dry_run(self, change_set: SourceChangeSet) -> DryRunObservation:
        """Preview the exact scoped patch against its optimistic base version."""
        self._validate(change_set)
        current = await self._transport.read_current(change_set)
        require_base(change_set, current)
        result = await self._transport.preview(change_set, current)
        if (
            result.change_set_digest != change_set.change_set_digest
            or result.desired_patch_digest != change_set.patch_digest()
        ):
            raise ChangeSetValidationError("dry-run observation binding mismatch")
        return result

    async def apply(self, change_set: SourceChangeSet) -> WriteBackAttempt:
        """Apply once, returning uncertainty rather than silently retrying."""
        self._validate(change_set)
        self._require_reconciled(change_set)
        prior = await self._transport.prior_effect(change_set)
        if prior is not None:
            require_effect(change_set, prior)
            return prior
        current = await self._transport.read_current(change_set)
        require_base(change_set, current)
        decision = await self._verifier.verify(change_set)
        require_authorized(change_set, decision)
        try:
            result = await self._transport.apply(change_set, current.source_version)
            require_effect(change_set, result)
            return result
        except OutcomeUncertainError:
            self._unresolved[change_set.idempotency_key] = change_set.change_set_digest
            return self._uncertain(change_set, current.source_version)

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Resolve possible effect; only a proven no-effect permits a retry."""
        self._validate(change_set)
        bound = self._unresolved.get(change_set.idempotency_key)
        if bound is not None and bound != change_set.change_set_digest:
            raise ReconciliationRequiredError(
                "idempotency key is bound to another uncertain change set"
            )
        result = await self._transport.reconcile(change_set)
        require_reconciliation(change_set, result)
        if result.effect_status is not WriteBackEffectStatus.OUTCOME_UNCERTAIN:
            self._unresolved.pop(change_set.idempotency_key, None)
        return result

    def _validate(self, change_set: SourceChangeSet) -> None:
        if change_set.change_set_digest != change_set.canonical_digest():
            raise ChangeSetValidationError("change-set digest does not match contents")
        if self._clock_ms() >= change_set.expires_at_ms:
            raise ChangeSetExpiredError("change set has expired")
        scope = change_set.field_scope
        if (
            len(scope) != len(set(scope))
            or set(scope) != set(change_set.desired_patch)
            or set(scope) != set(change_set.field_provenance)
        ):
            raise ChangeSetValidationError(
                "patch and provenance must exactly match field scope"
            )

    def _require_reconciled(self, change_set: SourceChangeSet) -> None:
        if change_set.idempotency_key in self._unresolved:
            raise ReconciliationRequiredError("uncertain outcome must reconcile first")

    @staticmethod
    def _uncertain(change_set: SourceChangeSet, version: str) -> WriteBackAttempt:
        authorization = change_set.authorization
        observation = f"{change_set.idempotency_key}:{version}:outcome_uncertain"
        provenance = json.dumps(
            change_set.field_provenance, sort_keys=True, separators=(",", ":")
        )
        return WriteBackAttempt(
            tenant_id=change_set.tenant_id,
            change_set_id=change_set.change_set_id,
            change_set_digest=change_set.change_set_digest,
            idempotency_key=change_set.idempotency_key,
            kind=WriteBackAttemptKind.APPLY,
            input_digest=authorization.input_digest,
            output_digest=authorization.output_digest,
            pre_source_version=version,
            post_source_version=version,
            applied_field_digest=change_set.patch_digest(),
            outcome=WriteBackOutcome.OUTCOME_UNCERTAIN,
            effect_status=WriteBackEffectStatus.OUTCOME_UNCERTAIN,
            connector_observation_digest=hashlib.sha256(
                observation.encode()
            ).hexdigest(),
            provenance_digest=hashlib.sha256(provenance.encode()).hexdigest(),
        )
