"""Bounded, fail-closed read-time access checks.

This is an SDK-local boundary. It does not claim an engine contract binding or
verify a principal; the composing host supplies authenticated identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import anyio

__all__ = ["AccessCheckAnswer", "AccessCheckPort", "BoundedAccessCheck"]

MAX_RECORD_REFS = 200
MAX_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class AccessCheckAnswer:
    """Complete partition of record references, as observed at a UTC time."""

    allowed: tuple[str, ...]
    denied: tuple[str, ...]
    checked_at: datetime


class AccessCheckPort(Protocol):
    """Read-only provider lookup; the caller authenticates the principal."""

    async def check(
        self, principal: str, record_refs: tuple[str, ...]
    ) -> AccessCheckAnswer: ...


class BoundedAccessCheck:
    """Validate provider replies and deny the whole batch on timeout."""

    def __init__(
        self, provider: AccessCheckPort, *, timeout_seconds: float = MAX_TIMEOUT_SECONDS
    ) -> None:
        if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("invalid access-check timeout")
        self._provider = provider
        self._timeout = timeout_seconds

    async def check(
        self, principal: str, record_refs: Sequence[str]
    ) -> AccessCheckAnswer:
        """Refuse ambiguous inputs and incomplete, contradictory provider replies."""
        refs = tuple(record_refs)
        if (
            not isinstance(principal, str)
            or not principal.strip()
            or len(refs) > MAX_RECORD_REFS
        ):
            raise ValueError("invalid access-check request")
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs) or len(
            set(refs)
        ) != len(refs):
            raise ValueError("invalid access-check record references")
        try:
            with anyio.fail_after(self._timeout):
                answer = await self._provider.check(principal, refs)
        except TimeoutError:
            return AccessCheckAnswer(
                allowed=(), denied=refs, checked_at=datetime.now(UTC)
            )
        if not isinstance(answer, AccessCheckAnswer):
            raise ValueError("invalid access-check answer")
        if (
            not isinstance(answer.allowed, tuple)
            or not isinstance(answer.denied, tuple)
            or not isinstance(answer.checked_at, datetime)
            or any(
                not isinstance(ref, str) for ref in (*answer.allowed, *answer.denied)
            )
        ):
            raise ValueError("invalid access-check answer")
        all_refs = (*answer.allowed, *answer.denied)
        if (
            answer.checked_at.utcoffset() is None
            or len(all_refs) != len(refs)
            or len(set(all_refs)) != len(all_refs)
            or set(all_refs) != set(refs)
        ):
            raise ValueError("incomplete or contradictory access-check answer")
        return answer
