"""Stream message and subscriber types."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class StreamMessage:
    """A single message in a real-time stream."""

    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    source: str = ""
    sequence: int = 0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_json(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "data": self.data,
                "timestamp": self.timestamp,
                "source": self.source,
                "sequence": self.sequence,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> StreamMessage:
        d = json.loads(raw)
        return cls(**d)


class StreamSubscriber(ABC):
    """Abstract base class for stream subscribers."""

    @abstractmethod
    async def on_message(self, message: StreamMessage) -> None:
        """Handle an incoming stream message."""

    @abstractmethod
    async def on_error(self, error: Exception) -> None:
        """Handle a stream error."""

    @abstractmethod
    async def on_disconnect(self) -> None:
        """Handle stream disconnection."""


class CallbackSubscriber(StreamSubscriber):
    """Subscriber that delegates to callback functions."""

    def __init__(
        self,
        on_message_fn: Callable[[StreamMessage], Any] | None = None,
        on_error_fn: Callable[[Exception], Any] | None = None,
        on_disconnect_fn: Callable[[], Any] | None = None,
    ):
        self._on_message = on_message_fn
        self._on_error = on_error_fn
        self._on_disconnect = on_disconnect_fn

    async def on_message(self, message: StreamMessage) -> None:
        if self._on_message:
            result = self._on_message(message)
            if asyncio.iscoroutine(result):
                await result

    async def on_error(self, error: Exception) -> None:
        if self._on_error:
            result = self._on_error(error)
            if asyncio.iscoroutine(result):
                await result

    async def on_disconnect(self) -> None:
        if self._on_disconnect:
            result = self._on_disconnect()
            if asyncio.iscoroutine(result):
                await result
