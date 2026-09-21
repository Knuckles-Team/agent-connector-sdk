"""The governed D18 ``WriteBackPort``."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.write_back import (
    ReconciliationObservation,
    SourceChangeSet,
    WriteBackAttempt,
)

from agent_connector_sdk.writeback.models import DryRunObservation, SourceSnapshot

__all__ = ["WriteBackPort"]


@runtime_checkable
class WriteBackPort(Protocol):
    """Read, preview, apply and reconcile one EG-owned source change set."""

    async def current_version(self, change_set: SourceChangeSet) -> SourceSnapshot:
        """Read current source state without mutation."""
        ...

    async def dry_run(self, change_set: SourceChangeSet) -> DryRunObservation:
        """Return the exact proposed field diff without mutation."""
        ...

    async def apply(self, change_set: SourceChangeSet) -> WriteBackAttempt:
        """Apply only after version and authorization checks succeed."""
        ...

    async def reconcile(self, change_set: SourceChangeSet) -> ReconciliationObservation:
        """Resolve a possible effect before retry or failover."""
        ...
