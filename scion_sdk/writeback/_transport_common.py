"""Compare-and-apply building blocks shared by the reference transports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAttemptKind,
    WriteBackEffectStatus,
    WriteBackOutcome,
    WriteBackReceiptPage,
    WriteBackReceiptRecord,
)

from scion_sdk.writeback.errors import IdempotencyConflictError
from scion_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = [
    "applied_attempt",
    "check_prior_effect",
    "digest",
    "preview_observation",
    "receipt_page",
    "reconciliation_observation",
]


def digest(value: object) -> str:
    """Canonical-JSON sha256 of ``value``."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def preview_observation(
    change_set: SourceChangeSet, current: SourceSnapshot
) -> DryRunObservation:
    """Scoped before/after values for ``change_set`` without mutation."""
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


def check_prior_effect(
    effect: WriteBackAttempt, change_set: SourceChangeSet
) -> WriteBackAttempt:
    """Return ``effect`` if it matches ``change_set`` exactly, else reject reuse."""
    if (
        effect.change_set_digest != change_set.change_set_digest
        or effect.applied_field_digest != change_set.patch_digest()
    ):
        raise IdempotencyConflictError("idempotency key is bound to a different effect")
    return effect


def applied_attempt(
    change_set: SourceChangeSet,
    *,
    pre_version: str,
    post_version: str,
    observation_digest: str,
) -> WriteBackAttempt:
    """The APPLIED attempt record for one committed compare-and-apply."""
    authorization = change_set.authorization
    return WriteBackAttempt(
        tenant_id=change_set.tenant_id,
        change_set_id=change_set.change_set_id,
        change_set_digest=change_set.change_set_digest,
        idempotency_key=change_set.idempotency_key,
        kind=WriteBackAttemptKind.APPLY,
        input_digest=authorization.input_digest,
        output_digest=authorization.output_digest,
        pre_source_version=pre_version,
        post_source_version=post_version,
        applied_field_digest=change_set.patch_digest(),
        outcome=WriteBackOutcome.APPLIED,
        effect_status=WriteBackEffectStatus.APPLIED,
        connector_observation_digest=observation_digest,
        provenance_digest=digest(change_set.field_provenance),
    )


def reconciliation_observation(
    change_set: SourceChangeSet,
    current: SourceSnapshot,
    status: WriteBackEffectStatus,
) -> ReconciliationObservation:
    """Reconciliation evidence for ``status`` against the current source."""
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
        evidence_digest=digest(evidence),
        connector_observation_digest=digest(current.model_dump()),
        provenance_digest=digest(change_set.field_provenance),
    )


def receipt_page(
    records: Sequence[WriteBackReceiptRecord],
    *,
    after_sequence: int | None,
    limit: int,
) -> WriteBackReceiptPage:
    """An ordered page of receipts strictly after ``after_sequence``."""
    after = after_sequence or 0
    remaining = [record for record in records if record.receipt.sequence > after]
    selected = remaining[:limit]
    next_sequence = selected[-1].receipt.sequence if len(remaining) > limit else None
    return WriteBackReceiptPage(receipts=selected, next_sequence=next_sequence)
