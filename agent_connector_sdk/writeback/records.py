"""Record shapes shared by every write-back transport and ledger implementation.

The in-memory fixture transport and the durable file transport (and their
ledgers) differ only in WHERE state lives; the observations they emit and the
receipt pages they serve are the same D18 contract, built here once.
"""

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

from agent_connector_sdk.writeback.errors import IdempotencyConflictError
from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot

# Only the receipt pager is a public seam (fakes in tests page the same way);
# the observation builders are shared by the package's own transports.
__all__ = ["receipt_page"]


def canonical_digest(value: object) -> str:
    """SHA-256 over sorted, compact JSON -- the digest every observation carries."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def scoped_preview(
    change_set: SourceChangeSet, current: SourceSnapshot
) -> DryRunObservation:
    """The scoped before/after values of ``change_set`` over ``current``."""
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


def matching_prior_effect(
    change_set: SourceChangeSet, effect: WriteBackAttempt | None
) -> WriteBackAttempt | None:
    """``effect`` when it is exactly this change set's; refuse a reused key."""
    if effect is None:
        return None
    if (
        effect.change_set_digest != change_set.change_set_digest
        or effect.applied_field_digest != change_set.patch_digest()
    ):
        raise IdempotencyConflictError("idempotency key is bound to a different effect")
    return effect


def applied_attempt(
    change_set: SourceChangeSet,
    current: SourceSnapshot,
    *,
    post_version: str,
    observation_digest: str,
) -> WriteBackAttempt:
    """The APPLIED attempt that moved ``current`` to ``post_version``."""
    authorization = change_set.authorization
    return WriteBackAttempt(
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
        connector_observation_digest=observation_digest,
        provenance_digest=canonical_digest(change_set.field_provenance),
    )


def reconciliation_observation(
    change_set: SourceChangeSet,
    current: SourceSnapshot,
    status: WriteBackEffectStatus,
) -> ReconciliationObservation:
    """What reconciliation observed for ``change_set`` at ``current``."""
    evidence = {"effect_status": status.value, "source_version": current.source_version}
    return ReconciliationObservation(
        tenant_id=change_set.tenant_id,
        change_set_id=change_set.change_set_id,
        change_set_digest=change_set.change_set_digest,
        idempotency_key=change_set.idempotency_key,
        observed_source_version=current.source_version,
        effect_status=status,
        retry_allowed=status is WriteBackEffectStatus.NO_EFFECT,
        evidence_digest=canonical_digest(evidence),
        connector_observation_digest=canonical_digest(current.model_dump()),
        provenance_digest=canonical_digest(change_set.field_provenance),
    )


def receipt_page(
    records: Sequence[WriteBackReceiptRecord],
    *,
    after_sequence: int | None,
    limit: int,
) -> WriteBackReceiptPage:
    """One ordered page of ``records`` after ``after_sequence`` (exclusive)."""
    after = after_sequence or 0
    remaining = [record for record in records if record.receipt.sequence > after]
    selected = remaining[:limit]
    next_sequence = selected[-1].receipt.sequence if len(remaining) > limit else None
    return WriteBackReceiptPage(receipts=selected, next_sequence=next_sequence)
