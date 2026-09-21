"""Authorization verifier used at the governed write-back seam."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAuthorizationDecision,
)

__all__ = ["AuthorizationVerifier"]


@runtime_checkable
class AuthorizationVerifier(Protocol):
    """Resolve a durable graph-os/EG authorization decision fail closed."""

    async def verify(
        self, change_set: SourceChangeSet
    ) -> WriteBackAuthorizationDecision:
        """Return a decision bound to ``change_set``; never infer a grant."""
        ...
