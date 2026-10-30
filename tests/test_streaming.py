"""Stream bus: topic and wildcard routing, ordering, history and isolated failures."""

from __future__ import annotations

import pytest

from scion_sdk.streaming import (
    CallbackSubscriber,
    StreamBus,
    StreamMessage,
    StreamSubscriber,
    WebSocketStreamAdapter,
)


def _collector() -> tuple[CallbackSubscriber, list[StreamMessage]]:
    received: list[StreamMessage] = []
    return CallbackSubscriber(on_message_fn=received.append), received


def test_message_json_round_trip() -> None:
    msg = StreamMessage(topic="t", data={"key": "value"}, source="unit")
    restored = StreamMessage.from_json(msg.to_json())
    assert (restored.topic, restored.data, restored.source) == (
        "t",
        {"key": "value"},
        "unit",
    )
    assert msg.timestamp


@pytest.mark.parametrize(
    ("pattern", "topics", "expected"),
    [
        ("market.AAPL", ["market.AAPL", "market.MSFT"], 1),
        ("market.*", ["market.AAPL", "market.MSFT", "system.health"], 2),
        ("*", ["anything", "else"], 2),
        ("specific", ["other"], 0),
    ],
)
async def test_routing_by_topic_pattern(
    pattern: str, topics: list[str], expected: int
) -> None:
    bus = StreamBus()
    subscriber, received = _collector()
    bus.subscribe(pattern, subscriber)
    delivered = [await bus.publish(StreamMessage(topic=topic)) for topic in topics]
    assert len(received) == sum(delivered) == expected


async def test_sequence_history_counts_and_unsubscribe() -> None:
    bus = StreamBus()
    subscriber, received = _collector()
    other = CallbackSubscriber()
    bus.subscribe("a", subscriber)
    bus.subscribe("b", other)
    bus.subscribe("b", subscriber)
    assert (bus.topic_count, bus.subscriber_count) == (2, 3)
    await bus.publish(StreamMessage(topic="a"))
    await bus.publish(StreamMessage(topic="a"))
    assert [m.sequence for m in received] == [1, 2]
    await bus.publish(StreamMessage(topic="b"))
    assert (len(bus.get_history()), len(bus.get_history("a"))) == (3, 2)
    bus.unsubscribe("a", subscriber)
    await bus.publish(StreamMessage(topic="a"))
    assert len(received) == 3


async def test_failing_subscriber_reports_its_error_and_others_still_receive() -> None:
    errors: list[Exception] = []

    def boom(_message: StreamMessage) -> None:
        raise ValueError("intentional")

    bus = StreamBus()
    good, received = _collector()
    bus.subscribe(
        "t", CallbackSubscriber(on_message_fn=boom, on_error_fn=errors.append)
    )
    bus.subscribe("t", good)
    assert await bus.publish(StreamMessage(topic="t")) == 1
    assert len(errors) == 1 and len(received) == 1


class _Socket:
    def __init__(self, frames: list[str]) -> None:
        self._frames = frames
        self.closed = False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for frame in self._frames:
            yield frame

    async def close(self) -> None:
        self.closed = True


async def test_websocket_frames_are_published_under_the_prefix() -> None:
    socket = _Socket([StreamMessage(topic="AAPL", data={"p": 1}).to_json(), "not json"])

    async def connect(_url: str) -> _Socket:
        return socket

    bus = StreamBus()
    subscriber, received = _collector()
    assert isinstance(subscriber, StreamSubscriber)
    bus.subscribe("market.*", subscriber)
    adapter = WebSocketStreamAdapter(bus, "wss://feed.example.test", connect=connect)
    assert await adapter.connect() and adapter.is_connected
    await adapter.listen(topic_prefix="market")
    assert [(m.topic, m.data) for m in received] == [("market.AAPL", {"p": 1})]
    await adapter.disconnect()
    assert socket.closed and not adapter.is_connected


async def test_unreachable_websocket_reports_false() -> None:
    async def connect(_url: str) -> None:
        raise OSError("refused")

    assert (
        await WebSocketStreamAdapter(StreamBus(), "wss://x", connect=connect).connect()
        is False
    )
