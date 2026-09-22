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

import hashlib
import json
from pathlib import Path
from typing import Any

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
)
from pydantic import JsonValue

from agent_connector_sdk.writeback.durable_files import read_json, write_json_atomic
from agent_connector_sdk.writeback.errors import (
    IdempotencyConflictError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = ["FileWriteBackTransport"]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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
        write_json_atomic(self._entities_path, entities)

    async def read_current(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read the durable entity snapshot."""
        return self._snapshot(change_set.entity_id)

    async def preview(
        self, change_set: SourceChangeSet, current: SourceSnapshot
    ) -> DryRunObservation:
        """Return the scoped before/after values without mutation."""
        before = {name: current.fields.get(name) for name in change_set.field_scope}
        after = {**before, **change_set.desired_patch}
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
        """Return an exactly matching prior durable effect or reject key reuse."""
        payload = self._read(self._effects_path).get(change_set.idempotency_key)
        if payload is None:
            return None
        effect = WriteBackAttempt.model_validate(payload)
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
        """CAS the durable source version and apply once."""
        current = self._snapshot(change_set.entity_id)
        if current.source_version != expected_version:
            raise SourceVersionConflictError("source changed during compare-and-apply")
        fields = {**current.fields, **change_set.desired_patch}
        post_version = f"{current.source_version}+1"
        self.seed(change_set.entity_id, post_version, fields)
        authorization = change_set.authorization
        attempt = WriteBackAttempt(
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
            connector_observation_digest=_digest({"fields": fields, "v": post_version}),
            provenance_digest=_digest(change_set.field_provenance),
        )
        effects = self._read(self._effects_path)
        effects[change_set.idempotency_key] = attempt.model_dump(mode="json")
        write_json_atomic(self._effects_path, effects)
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
            evidence_digest=_digest(evidence),
            connector_observation_digest=_digest(current.model_dump()),
            provenance_digest=_digest(change_set.field_provenance),
        )

    def _snapshot(self, entity_id: str) -> SourceSnapshot:
        payload = self._read(self._entities_path)[entity_id]
        return SourceSnapshot(
            source_version=str(payload["source_version"]), fields=payload["fields"]
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        return read_json(path) or {}
