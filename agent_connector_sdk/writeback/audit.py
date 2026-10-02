"""Reference in-memory audit reservation for write-back fixtures."""

from __future__ import annotations

from epistemic_graph.generated.write_back import SourceChangeSet

from agent_connector_sdk.writeback.errors import AuditReservationUnavailableError

__all__ = ["InMemoryAuditReservation"]


class InMemoryAuditReservation:
    """Fixture audit reservation log, not a durable production store.

    A production implementation resolves a durable reservation (for example
    through the operator's audit system) before the first real source call
    for a change set and reuses it across a proven-no-effect retry.
    """

    def __init__(self) -> None:
        self._reservations: dict[str, str] = {}
        self._deny: set[str] = set()

    def deny_next(self, idempotency_key: str) -> None:
        """Make the next reservation for this idempotency key unavailable."""
        self._deny.add(idempotency_key)

    async def reserve(self, change_set: SourceChangeSet) -> str:
        """Return the existing reservation for this key, or take a new one."""
        key = change_set.idempotency_key
        if key in self._deny:
            self._deny.discard(key)
            raise AuditReservationUnavailableError(
                "audit reservation is unavailable for this idempotency key"
            )
        existing = self._reservations.get(key)
        if existing is not None:
            return existing
        reservation_id = f"audit:{key}:{change_set.change_set_digest}"
        self._reservations[key] = reservation_id
        return reservation_id
