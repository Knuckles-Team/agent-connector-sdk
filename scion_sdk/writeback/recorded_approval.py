"""Resolve an independent graph-owned approval for an exact write-back."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from epistemic_graph.generated.models import GovernedChange, GovernedStatus
from epistemic_graph.generated.security import send_governed_change
from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAuthorizationDecision,
)

from scion_sdk.ports.writeback_ledger import WriteBackLedger
from scion_sdk.writeback.authorization import _require_durable_authorization
from scion_sdk.writeback.errors import AuthorizationDeniedError


def write_back_approval_target(change_set: SourceChangeSet) -> str:
    """Bind tenant and change-set identity without delimiter ambiguity."""
    encoded = json.dumps(
        [change_set.tenant_id, change_set.change_set_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    return "write-back:" + hashlib.sha256(encoded).hexdigest()


def _approval_binds(
    approval: GovernedChange,
    decision: WriteBackAuthorizationDecision,
    change_set: SourceChangeSet,
    target: str,
    now: int,
) -> bool:
    """True when the approval is active, independent and bound to this change."""
    return (
        _approval_identity_matches(approval, decision, change_set, target)
        and _approval_is_independent(approval, change_set)
        and _approval_is_live(approval, change_set, now)
    )


def _approval_identity_matches(
    approval: GovernedChange,
    decision: WriteBackAuthorizationDecision,
    change_set: SourceChangeSet,
    target: str,
) -> bool:
    return (
        approval.change_id == decision.authorization_ref
        and approval.kind == "governed.write-back"
        and approval.target == target
        and approval.digest == change_set.change_set_digest
    )


def _approval_is_independent(
    approval: GovernedChange, change_set: SourceChangeSet
) -> bool:
    return (
        approval.status is GovernedStatus.APPROVED
        and bool(approval.approver)
        and approval.approver != approval.proposer
        and approval.proposer == change_set.actor
    )


def _approval_is_live(
    approval: GovernedChange, change_set: SourceChangeSet, now: int
) -> bool:
    return (
        approval.approved_until_ms is not None
        and now < approval.approved_until_ms
        and now < change_set.expires_at_ms
    )


class RecordedApprovalResolver:
    """Require a separately approved EG governed-change record.

    This resolver verifies an approval fact. It does not provide the durable
    effect reservation or cross-process replay fence needed for a new effect.
    """

    def __init__(
        self,
        ledger: WriteBackLedger,
        client: Any,
        *,
        graph: str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._ledger = ledger
        self._client = client
        self._graph = graph
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    async def verify(
        self, change_set: SourceChangeSet
    ) -> WriteBackAuthorizationDecision:
        """Refuse unless EG records an active approval of this exact digest."""
        durable = await self._ledger.get(change_set.tenant_id, change_set.change_set_id)
        decision = _require_durable_authorization(change_set, durable)
        approval, target = await self._load_approval(change_set, decision)
        if not _approval_binds(
            approval, decision, change_set, target, self._clock_ms()
        ):
            raise AuthorizationDeniedError("recorded approval binding mismatch")
        return decision

    async def _load_approval(
        self, change_set: SourceChangeSet, decision: WriteBackAuthorizationDecision
    ) -> tuple[GovernedChange, str]:
        try:
            target = write_back_approval_target(change_set)
            response = await send_governed_change(
                self._client,
                {"op": {"op": "get", "change_id": decision.authorization_ref}},
                self._graph,
            )
            return GovernedChange.model_validate(response.payload), target
        except Exception:
            raise AuthorizationDeniedError("recorded approval unavailable") from None
