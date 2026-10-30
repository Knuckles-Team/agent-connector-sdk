"""In-process topic pub/sub bus."""

from __future__ import annotations

import logging
from collections import defaultdict

from scion_sdk._stream_types import StreamMessage, StreamSubscriber

logger = logging.getLogger(__name__)


class StreamBus:
    """
    In-process pub/sub message bus for real-time streaming.

    This is the core routing layer — domain-specific adapters (market data,
    telemetry, agent events) publish to topics, and subscribers receive
    filtered messages. Designed to be extended with WebSocket transport.

    Usage:
        bus = StreamBus()
        bus.subscribe("market.AAPL.trades", my_subscriber)
        await bus.publish(StreamMessage(topic="market.AAPL.trades", data={...}))
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[StreamSubscriber]] = defaultdict(list)
        self._sequence: int = 0
        self._running = False
        self._history: list[StreamMessage] = []
        self._max_history: int = 1000

    def subscribe(self, topic: str, subscriber: StreamSubscriber) -> None:
        """Subscribe to a topic pattern. Supports exact match and wildcard '*'."""
        self._subscribers[topic].append(subscriber)
        logger.debug(f"Subscribed to topic: {topic}")

    def unsubscribe(self, topic: str, subscriber: StreamSubscriber) -> None:
        """Remove a subscriber from a topic."""
        if topic in self._subscribers:
            self._subscribers[topic] = [
                s for s in self._subscribers[topic] if s is not subscriber
            ]

    async def publish(self, message: StreamMessage) -> int:
        """
        Publish a message to all matching subscribers.

        Returns:
            Number of subscribers that received the message.
        """
        self._sequence += 1
        message.sequence = self._sequence

        # Store in history
        self._history.append(message)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        delivered = 0
        for pattern, subscribers in self._subscribers.items():
            if self._matches(pattern, message.topic):
                delivered += await self._deliver(subscribers, message)
        return delivered

    async def _deliver(
        self, subscribers: list[StreamSubscriber], message: StreamMessage
    ) -> int:
        delivered = 0
        for subscriber in subscribers:
            try:
                await subscriber.on_message(message)
            except Exception as exc:
                await self._report_failure(subscriber, message, exc)
            else:
                delivered += 1
        return delivered

    async def _report_failure(
        self, subscriber: StreamSubscriber, message: StreamMessage, exc: Exception
    ) -> None:
        logger.error(
            "subscriber failed on topic %s (%s)", message.topic, type(exc).__name__
        )
        try:
            await subscriber.on_error(exc)
        except Exception as handler_exc:
            logger.error(
                "subscriber error handler failed (%s)", type(handler_exc).__name__
            )

    def _matches(self, pattern: str, topic: str) -> bool:
        """Check if a topic matches a subscription pattern (supports '*' wildcard)."""
        if pattern == topic:
            return True
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return topic.startswith(prefix + ".")
        return False

    @property
    def topic_count(self) -> int:
        """Number of subscribed topics."""
        return len(self._subscribers)

    @property
    def subscriber_count(self) -> int:
        """Total number of subscribers across all topics."""
        return sum(len(subs) for subs in self._subscribers.values())

    def get_history(
        self, topic: str | None = None, limit: int = 100
    ) -> list[StreamMessage]:
        """Get recent message history, optionally filtered by topic."""
        if topic:
            filtered = [m for m in self._history if self._matches(topic, m.topic)]
        else:
            filtered = self._history
        return filtered[-limit:]
