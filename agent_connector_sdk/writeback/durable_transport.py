"""A durable, file-backed reference ``WriteBackTransport`` for restart proofs.

A real writable connector's source system (ServiceNow, ERPNext, LeanIX, ...)
stays durable across an SDK process crash because it is a separate service
with its own storage. This reference transport represents that property on
disk instead of in a real vendor API, so an SDK-repo-local integration test
can prove ``DurableWritableConnector``'s restart contract (writeback/
connector.py) end to end without depending on a fleet connector's live
credentials. See :class:`~agent_connector_sdk.writeback.memory.
InMemoryWriteBackTransport` for the same compare-and-apply shape kept only in
process memory, which a killed process cannot use to prove anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackEffectStatus,
)
from pydantic import JsonValue

from agent_connector_sdk.writeback.durable_files import _read_json, _write_json_atomic
from agent_connector_sdk.writeback.errors import (
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

__all__ = ["FileWriteBackTransport"]


class FileWriteBackTransport:
    """A compare-and-apply source entity durable to the local filesystem."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._entities_path = directory / "entities.json"
        self._effects_path = directory / "effects.json"

    def seed(
        self, entity_id: str, source_version: str, fields: dict[str, JsonValue]
    ) -> None:
        """Create or replace one entity's current durable state."""
        entities = self._read(self._entities_path)
        entities[entity_id] = {"source_version": source_version, "fields": fields}
        _write_json_atomic(self._entities_path, entities)

    async def read_current(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read the durable entity snapshot."""
        return self._snapshot(change_set.entity_id)

    async def preview(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> DryRunObservation:
        """Return the scoped before/after values without mutation."""
        return scoped_preview(change_set, current)

    async def prior_effect(
        self, change_set: SourceChangeSet
    ) -> WriteBackAttempt | None:
        """Return an exactly matching prior durable effect or reject key reuse."""
        payload = self._read(self._effects_path).get(change_set.idempotency_key)
        effect = None if payload is None else WriteBackAttempt.model_validate(payload)
        return matching_prior_effect(change_set, effect)

    async def apply(
        self, change_set: SourceChangeSet, expected_version: str
    ) -> WriteBackAttempt:
        """CAS the durable source version and apply once."""
        current = self._snapshot(change_set.entity_id)
        if current.source_version != expected_version:
            raise SourceVersionConflictError("source changed during compare-and-apply")
        fields = {**current.fields, **change_set.desired_patch}
        post_version = f"{current.source_version}+1"
        self.seed(change_set.entity_id, post_version, fields)
        attempt = applied_attempt(
            change_set,
            current,
            post_version=post_version,
            observation_digest=canonical_digest({"fields": fields, "v": post_version}),
        )
        effects = self._read(self._effects_path)
        effects[change_set.idempotency_key] = attempt.model_dump(mode="json")
        _write_json_atomic(self._effects_path, effects)
        return attempt

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Resolve by durable idempotency key and current durable source version."""
        effect = self._read(self._effects_path).get(change_set.idempotency_key)
        current = self._snapshot(change_set.entity_id)
        status = (
            WriteBackEffectStatus.APPLIED
            if effect is not None
            else WriteBackEffectStatus.NO_EFFECT
        )
        return reconciliation_observation(change_set, current, status)

    def _snapshot(self, entity_id: str) -> SourceSnapshot:
        payload = self._read(self._entities_path)[entity_id]
        return SourceSnapshot(
            source_version=str(payload["source_version"]), fields=payload["fields"]
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        return _read_json(path) or {}
