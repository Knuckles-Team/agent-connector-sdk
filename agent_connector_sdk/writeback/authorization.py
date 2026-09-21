"""Deterministic authorization verifier for fixtures and connector tests."""

from __future__ import annotations

from dataclasses import dataclass

from epistemic_graph.generated.write_back import (
    SourceChangeSet,
    WriteBackAuthorizationDecision,
)

from agent_connector_sdk.writeback.errors import AuthorizationDeniedError

__all__ = ["DeterministicAuthorizationVerifier"]


@dataclass(frozen=True)
class _AuthorizationBinding:
    change_set_digest: str
    mode: str
    authorization_ref: str
    policy_digest: str
    decision_digest: str
    input_digest: str
    output_digest: str


def _binding(change_set: SourceChangeSet) -> _AuthorizationBinding:
    authorization = change_set.authorization
    return _AuthorizationBinding(
        change_set_digest=change_set.change_set_digest,
        mode=authorization.mode.value,
        authorization_ref=authorization.authorization_ref,
        policy_digest=change_set.policy_digest,
        decision_digest=authorization.decision_digest,
        input_digest=authorization.input_digest,
        output_digest=authorization.output_digest,
    )


class DeterministicAuthorizationVerifier:
    """Fail closed unless an exact effect binding was granted in advance.

    This is a reference verifier for fixtures, not a production policy store.
    Production implementations resolve graph-os/EG's durable decision using
    the same complete digest/mode/reference/policy/schema binding.
    """

    def __init__(self) -> None:
        self._grants: set[_AuthorizationBinding] = set()

    def grant(self, change_set: SourceChangeSet) -> None:
        """Allow exactly this canonical authorization binding."""
        binding = _binding(change_set)
        if not binding.authorization_ref or not binding.policy_digest:
            raise AuthorizationDeniedError(
                "authorization reference and policy digest must not be empty"
            )
        self._grants.add(binding)

    async def verify(
        self, change_set: SourceChangeSet
    ) -> WriteBackAuthorizationDecision:
        """Return an exact decision or refuse; mode/reference alone never grant."""
        binding = _binding(change_set)
        if binding not in self._grants:
            raise AuthorizationDeniedError("no exact authorization decision")
        return change_set.authorization
