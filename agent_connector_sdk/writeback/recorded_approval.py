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

from agent_connector_sdk.ports.writeback_ledger import WriteBackLedger
from agent_connector_sdk.writeback.authorization import _require_durable_authorization
from agent_connector_sdk.writeback.errors import AuthorizationDeniedError


def write_back_approval_target(change_set: SourceChangeSet) -> str:
    """Bind tenant and change-set identity without delimiter ambiguity."""
    encoded = json.dumps(
        [change_set.tenant_id, change_set.change_set_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    return "write-back:" + hashlib.sha256(encoded).hexdigest()


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
        try:
            target = write_back_approval_target(change_set)
            response = await send_governed_change(
                self._client,
                {"op": {"op": "get", "change_id": decision.authorization_ref}},
                self._graph,
            )
            approval = GovernedChange.model_validate(response.payload)
        except Exception:
            raise AuthorizationDeniedError("recorded approval unavailable") from None
        now = self._clock_ms()
        if (
            approval.change_id != decision.authorization_ref
            or approval.kind != "governed.write-back"
            or approval.target != target
            or approval.digest != change_set.change_set_digest
            or approval.status is not GovernedStatus.APPROVED
            or not approval.approver
            or approval.approver == approval.proposer
            or approval.proposer != change_set.actor
            or approval.approved_until_ms is None
            or now >= approval.approved_until_ms
            or now >= change_set.expires_at_ms
        ):
            raise AuthorizationDeniedError("recorded approval binding mismatch")
        return decision
