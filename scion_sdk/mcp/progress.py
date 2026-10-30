"""Serialized, request-local progress delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from scion_sdk.mcp.context import ToolExecutionContext, ToolProgress

__all__ = ["PROGRESS_SEND_TIMEOUT", "OrderedProgress"]

PROGRESS_SEND_TIMEOUT = 5.0


class OrderedProgress:
    """Serialize per-request progress; the caller supplies the redactor and sender."""

    def __init__(
        self,
        context: ToolExecutionContext,
        sender: Callable[[str | int, ToolProgress], Awaitable[None]],
        redact: Callable[[str], str],
        *,
        send_timeout: float = PROGRESS_SEND_TIMEOUT,
    ) -> None:
        if not 0 < send_timeout <= PROGRESS_SEND_TIMEOUT:
            raise ValueError("invalid progress send timeout")
        self._context = context
        self._sender = sender
        self._redact = redact
        self._timeout = send_timeout
        self._lock = asyncio.Lock()
        self._last: ToolProgress | None = None
        self._finished = False

    @property
    def last(self) -> ToolProgress | None:
        """Return the last accepted, redacted progress summary."""
        return self._last

    async def update(
        self,
        completed: float,
        *,
        total: float | None = None,
        message: str | None = None,
    ) -> ToolProgress | None:
        """Accept one increasing summary and await its bounded notification."""
        async with self._lock:
            self._check_transition(completed, total)
            sequence = self._last.sequence + 1 if self._last else 1
            safe_message = self._redact(message) if message is not None else None
            progress = ToolProgress(
                sequence=sequence,
                completed=completed,
                total=total,
                message=safe_message,
            )
            remaining = (self._context.deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError("progress deadline exceeded")
            if self._last is not None and completed == self._last.completed:
                self._last = progress.model_copy(
                    update={"sequence": self._last.sequence}
                )
                return None
            self._last = progress
            if self._context.progress_token is not None:
                async with asyncio.timeout(min(remaining, self._timeout)):
                    await self._sender(self._context.progress_token, progress)
            return progress

    def _check_transition(self, completed: float, total: float | None) -> None:
        if self._finished:
            raise ValueError("progress is terminal")
        if self._last is not None:
            if self._last.total is not None and total != self._last.total:
                raise ValueError("progress total changed")
            if completed < self._last.completed:
                raise ValueError("progress decreased")

    async def finish(self) -> ToolProgress | None:
        """Mark progress terminal and return its last accepted summary."""
        async with self._lock:
            self._finished = True
            return self._last
