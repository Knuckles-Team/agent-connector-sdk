"""Stage event identities until the worker confirms page acceptance."""

from __future__ import annotations

from scion_sdk.adapters.event_identity import EventIdentityTracker
from scion_sdk.contracts import RecordPage
from scion_sdk.ports.errors import SourceContractError


class _EventPageIdentity:
    """Serialize extraction and commit a candidate only for its accepted page."""

    def __init__(self) -> None:
        self.tracker = EventIdentityTracker()
        self._extracting = False
        self._pending: tuple[RecordPage, EventIdentityTracker] | None = None

    def begin(self) -> EventIdentityTracker:
        if self._extracting or self._pending is not None:
            raise SourceContractError("event feed already has an unfinished page")
        self._extracting = True
        return self.tracker.fork()

    def stage(self, page: RecordPage, candidate: EventIdentityTracker) -> None:
        self._pending = (page, candidate)

    def end(self) -> None:
        self._extracting = False

    def finish(self, page: RecordPage, *, accepted: bool) -> None:
        if self._pending is None or self._pending[0] is not page:
            raise SourceContractError("event feed page completion does not match")
        if accepted:
            self.tracker.merge(self._pending[1])
        self._pending = None
