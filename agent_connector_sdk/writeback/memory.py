"""Reference in-memory source transport for write-back fixtures."""

from __future__ import annotations

from enum import StrEnum

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackEffectStatus,
)
from pydantic import JsonValue

from agent_connector_sdk.writeback.errors import (
    IdempotencyConflictError,
    OutcomeUncertainError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot
from agent_connector_sdk.writeback.records import (
    applied_attempt,
    canonical_digest,
    matching_prior_effect,
    reconciliation_observation,
    scoped_preview,
)

__all__ = ["FixtureUncertainty", "InMemoryWriteBackTransport"]


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
        return scoped_preview(change_set, current)

    async def prior_effect(
        self, change_set: SourceChangeSet
    ) -> WriteBackAttempt | None:
        """Return an exactly matching prior effect or reject key reuse."""
        return matching_prior_effect(
            change_set, self.effects.get(change_set.idempotency_key)
        )

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
        return reconciliation_observation(change_set, current, status)

    def _commit(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> WriteBackAttempt:
        fields = dict(current.fields)
        fields.update(change_set.desired_patch)
        post_version = f"{current.source_version}+1"
        snapshot = SourceSnapshot(source_version=post_version, fields=fields)
        self.entities[change_set.entity_id] = snapshot
        observation = applied_attempt(
            change_set,
            current,
            post_version=post_version,
            observation_digest=canonical_digest(snapshot.model_dump()),
        )
        self.effects[change_set.idempotency_key] = observation
        return observation
