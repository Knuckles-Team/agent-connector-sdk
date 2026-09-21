"""Binding checks for canonical EG write-back observations."""

from __future__ import annotations

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
    WriteBackAttemptKind,
    WriteBackAuthorizationDecision,
    WriteBackEffectStatus,
    WriteBackOutcome,
)

from agent_connector_sdk.writeback.errors import (
    AuthorizationDeniedError,
    ChangeSetValidationError,
    SourceVersionConflictError,
)
from agent_connector_sdk.writeback.models import SourceSnapshot

__all__ = [
    "require_authorized",
    "require_base",
    "require_effect",
    "require_reconciliation",
]


def require_base(change_set: SourceChangeSet, current: SourceSnapshot) -> None:
    """Reject a stale optimistic source version before mutation."""
    if current.source_version != change_set.base_source_version:
        raise SourceVersionConflictError("source version changed before mutation")


def require_authorized(
    change_set: SourceChangeSet, decision: WriteBackAuthorizationDecision
) -> None:
    """Require the verifier's exact nested EG authorization decision."""
    if not decision.authorized or decision != change_set.authorization:
        raise AuthorizationDeniedError("authorization decision binding mismatch")


def require_effect(change_set: SourceChangeSet, result: WriteBackAttempt) -> None:
    """Require an applied attempt bound to the exact canonical change set."""
    expected = (
        change_set.tenant_id,
        change_set.change_set_id,
        change_set.change_set_digest,
        change_set.idempotency_key,
        change_set.authorization.input_digest,
        change_set.authorization.output_digest,
        change_set.patch_digest(),
    )
    observed = (
        result.tenant_id,
        result.change_set_id,
        result.change_set_digest,
        result.idempotency_key,
        result.input_digest,
        result.output_digest,
        result.applied_field_digest,
    )
    if (
        observed != expected
        or result.kind is not WriteBackAttemptKind.APPLY
        or result.outcome is not WriteBackOutcome.APPLIED
        or result.effect_status is not WriteBackEffectStatus.APPLIED
    ):
        raise ChangeSetValidationError("apply observation binding mismatch")


def require_reconciliation(
    change_set: SourceChangeSet, result: ReconciliationObservation
) -> None:
    """Require reconciliation identity and retry semantics to agree."""
    expected = (
        change_set.tenant_id,
        change_set.change_set_id,
        change_set.change_set_digest,
        change_set.idempotency_key,
    )
    observed = (
        result.tenant_id,
        result.change_set_id,
        result.change_set_digest,
        result.idempotency_key,
    )
    if observed != expected:
        raise ChangeSetValidationError("reconciliation binding mismatch")
    if result.effect_status is WriteBackEffectStatus.APPLIED and result.retry_allowed:
        raise ChangeSetValidationError("an applied effect cannot be retryable")
    if (
        result.effect_status is WriteBackEffectStatus.NO_EFFECT
        and not result.retry_allowed
    ):
        raise ChangeSetValidationError("a proven no-effect must permit retry")
