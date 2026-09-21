"""Reference in-memory source transport for write-back fixtures."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
)
from pydantic import JsonValue

from agent_connector_sdk.writeback.errors import (
    IdempotencyConflictError,
    OutcomeUncertainError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = ["FixtureUncertainty", "InMemoryWriteBackTransport"]


def _fixture_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class FixtureUncertainty(StrEnum):
    """Where a fixture transport loses its acknowledgement."""

    BEFORE_EFFECT = "before_effect"
    AFTER_EFFECT = "after_effect"
    UNRESOLVED = "unresolved"


class InMemoryWriteBackTransport:
    """A compare-and-apply transport with deterministic failure injection."""

    def __init__(self) -> None:
        self.entities: dict[str, SourceSnapshot] = {}
        self.effects: dict[str, WriteBackAttempt] = {}
        self.attempts = 0
        self._uncertainty: dict[str, FixtureUncertainty] = {}

    def seed(
        self, entity_id: str, source_version: str, fields: dict[str, JsonValue]
    ) -> None:
        """Create or replace a fixture entity."""
        self.entities[entity_id] = SourceSnapshot(
            source_version=source_version, fields=fields
        )

    def inject_uncertainty(
        self, idempotency_key: str, outcome: FixtureUncertainty
    ) -> None:
        """Make the next matching apply lose its acknowledgement."""
        self._uncertainty[idempotency_key] = outcome

    async def read_current(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read the fixture entity."""
        return self.entities[change_set.entity_id]

    async def preview(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> DryRunObservation:
        """Return the scoped before/after values without mutation."""
        before = {name: current.fields.get(name) for name in change_set.field_scope}
        after = dict(before)
        after.update(change_set.desired_patch)
        changed = tuple(
            name for name in change_set.field_scope if before[name] != after[name]
        )
        return DryRunObservation(
            change_set_digest=change_set.change_set_digest,
            source_version=current.source_version,
            desired_patch_digest=change_set.patch_digest(),
            changed_fields=changed,
            before=before,
            after=after,
        )

    async def prior_effect(
        self, change_set: SourceChangeSet
    ) -> WriteBackAttempt | None:
        """Return an exactly matching prior effect or reject key reuse."""
        effect = self.effects.get(change_set.idempotency_key)
        if effect is None:
            return None
        if (
            effect.change_set_digest != change_set.change_set_digest
            or effect.applied_field_digest != change_set.patch_digest()
        ):
            raise IdempotencyConflictError(
                "idempotency key is bound to a different effect"
            )
        return effect

    async def apply(
        self, change_set: SourceChangeSet, expected_version: str
    ) -> WriteBackAttempt:
        """CAS the source version, apply once, and optionally lose acknowledgement."""
        self.attempts += 1
        uncertainty = self._uncertainty.get(change_set.idempotency_key)
        if uncertainty is FixtureUncertainty.BEFORE_EFFECT:
            self._uncertainty.pop(change_set.idempotency_key)
            raise OutcomeUncertainError("fixture lost acknowledgement before effect")
        if uncertainty is FixtureUncertainty.UNRESOLVED:
            raise OutcomeUncertainError("fixture outcome remains unresolved")
        current = self.entities[change_set.entity_id]
        if current.source_version != expected_version:
            raise SourceVersionConflictError("source changed during compare-and-apply")
        observation = self._commit(change_set, current)
        if uncertainty is FixtureUncertainty.AFTER_EFFECT:
            self._uncertainty.pop(change_set.idempotency_key)
            raise OutcomeUncertainError("fixture lost acknowledgement after effect")
        return observation

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Resolve injected before/after-effect outcomes by key and source version."""
        uncertainty = self._uncertainty.get(change_set.idempotency_key)
        effect = self.effects.get(change_set.idempotency_key)
        if uncertainty is FixtureUncertainty.UNRESOLVED:
            status = WriteBackEffectStatus.OUTCOME_UNCERTAIN
        elif effect is not None:
            if effect.change_set_digest != change_set.change_set_digest:
                raise IdempotencyConflictError(
                    "idempotency key is bound to a different effect"
                )
            status = WriteBackEffectStatus.APPLIED
        else:
            status = WriteBackEffectStatus.NO_EFFECT
        if uncertainty is not FixtureUncertainty.UNRESOLVED:
            self._uncertainty.pop(change_set.idempotency_key, None)
        current = self.entities[change_set.entity_id]
        evidence = {
            "effect_status": status.value,
            "source_version": current.source_version,
        }
        return ReconciliationObservation(
            tenant_id=change_set.tenant_id,
            change_set_id=change_set.change_set_id,
            change_set_digest=change_set.change_set_digest,
            idempotency_key=change_set.idempotency_key,
            observed_source_version=current.source_version,
            effect_status=status,
            retry_allowed=status is WriteBackEffectStatus.NO_EFFECT,
            evidence_digest=_fixture_digest(evidence),
            connector_observation_digest=_fixture_digest(current.model_dump()),
            provenance_digest=_fixture_digest(change_set.field_provenance),
        )

    def _commit(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> WriteBackAttempt:
        fields = dict(current.fields)
        fields.update(change_set.desired_patch)
        post_version = f"{current.source_version}+1"
        snapshot = SourceSnapshot(source_version=post_version, fields=fields)
        self.entities[change_set.entity_id] = snapshot
        authorization = change_set.authorization
        observation = WriteBackAttempt(
            tenant_id=change_set.tenant_id,
            change_set_id=change_set.change_set_id,
            change_set_digest=change_set.change_set_digest,
            idempotency_key=change_set.idempotency_key,
            kind=WriteBackAttemptKind.APPLY,
            input_digest=authorization.input_digest,
            output_digest=authorization.output_digest,
            pre_source_version=current.source_version,
            post_source_version=post_version,
            applied_field_digest=change_set.patch_digest(),
            outcome=WriteBackOutcome.APPLIED,
            effect_status=WriteBackEffectStatus.APPLIED,
            connector_observation_digest=_fixture_digest(snapshot.model_dump()),
            provenance_digest=_fixture_digest(change_set.field_provenance),
        )
        self.effects[change_set.idempotency_key] = observation
        return observation
