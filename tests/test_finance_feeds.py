"""Market feeds: live OHLCV bars from ticks, per-symbol fan-out and one-shot alerts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scion_sdk.finance import feeds
from scion_sdk.finance.feeds import (
    LiveBar,
    MarketFeedBus,
    Tick,
    TickAggregator,
)


def test_live_bar_tracks_ohlcv_across_ticks() -> None:
    bar = LiveBar(symbol="AAPL")
    assert bar.is_empty
    for price, volume in ((100.0, 500), (105.0, 300), (98.0, 200)):
        bar.update(Tick(symbol="AAPL", price=price, volume=volume))
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 105.0, 98.0, 98.0)
    assert (bar.volume, bar.tick_count) == (1000, 3)
    assert bar.to_dict()["open"] == 100.0


def test_aggregator_accumulates_ticks_into_the_current_bar() -> None:
    agg = TickAggregator(symbol="AAPL", bar_size_seconds=3600)
    agg.on_tick(Tick(symbol="AAPL", price=100.0, volume=100))
    agg.on_tick(Tick(symbol="AAPL", price=110.0, volume=200))
    assert agg.total_ticks == 2
    assert (agg.current_bar.tick_count, agg.current_bar.high) == (2, 110.0)


async def test_ticks_fan_out_by_symbol() -> None:
    bus = MarketFeedBus()
    seen: dict[str, list[object]] = {"AAPL": [], "MSFT": []}
    for symbol, sink in seen.items():
        bus.subscribe_ticks(symbol, sink.append)
    await bus.publish_tick(Tick(symbol="AAPL", price=150.0))
    await bus.publish_tick(Tick(symbol="MSFT", price=300.0))
    assert [len(v) for v in seen.values()] == [1, 1]
    assert bus.total_ticks == 2


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.3")
async def test_market_feed_defaults_to_sdk_stream_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stream_bus = feeds.StreamBus

    class _SDKStreamBus(real_stream_bus):
        pass

    monkeypatch.setattr(feeds, "StreamBus", _SDKStreamBus)
    bus = MarketFeedBus()
    received: list[object] = []
    bus.subscribe_ticks("AAPL", received.append)

    delivered = await bus.publish_tick(Tick(symbol="AAPL", price=150.0))

    assert isinstance(bus.bus, _SDKStreamBus)
    assert delivered == 1
    assert len(received) == 1
    assert received[0].topic == "market.AAPL.ticks"
    assert bus.bus.get_history("market.AAPL.ticks")[0] is received[0]


async def test_bar_subscription_tracks_the_symbol() -> None:
    bus = MarketFeedBus()
    bus.subscribe_bars("AAPL", 60, lambda _bar: None)
    await bus.publish_tick(Tick(symbol="AAPL", price=1.0))
    assert bus.active_symbols == ["AAPL"]


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.7")
async def test_bar_subscriptions_use_independent_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock:
        second = 0

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            del tz
            return datetime.fromtimestamp(cls.second, UTC)

    monkeypatch.setattr(feeds, "datetime", Clock)
    bus = MarketFeedBus()
    short: list[object] = []
    short_second: list[object] = []
    long: list[object] = []
    bus.subscribe_bars("AAPL", 60, short.append)
    bus.subscribe_bars("AAPL", 60, short_second.append)
    bus.subscribe_bars("AAPL", 300, long.append)
    await bus.publish_tick(Tick(symbol="AAPL", price=1.0))
    Clock.second = 61
    await bus.publish_tick(Tick(symbol="AAPL", price=2.0))
    assert len(short) == 1
    assert long == []
    Clock.second = 301
    await bus.publish_tick(Tick(symbol="AAPL", price=3.0))
    assert len(short) == 2
    assert short_second == short
    assert len(long) == 1
    assert bus.active_symbols == ["AAPL"]


@pytest.mark.parametrize(
    ("direction", "threshold", "prices", "fired"),
    [
        ("above", 155.0, (150.0, 160.0, 170.0), 1),
        ("below", 100.0, (110.0, 95.0, 90.0), 1),
        ("above", 200.0, (150.0,), 0),
    ],
)
async def test_price_alert_fires_once_when_crossed(
    direction: str, threshold: float, prices: tuple[float, ...], fired: int
) -> None:
    bus = MarketFeedBus()
    alerts: list[object] = []
    bus.add_price_alert("AAPL", threshold, direction, alerts.append)
    assert bus.pending_alerts == 1
    for price in prices:
        await bus.publish_tick(Tick(symbol="AAPL", price=price))
    assert len(alerts) == fired


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.9")
@pytest.mark.parametrize("size", [0, -1, True, 0.5])
def test_invalid_bar_interval_refuses_without_subscribing(size: int) -> None:
    bus = MarketFeedBus()
    with pytest.raises(ValueError, match="positive integer"):
        bus.subscribe_bars("AAPL", size, lambda _bar: None)
    assert bus.active_symbols == []
    assert bus.bus.subscriber_count == 0
    with pytest.raises(ValueError, match="positive integer"):
        TickAggregator("AAPL", size)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.10")
@pytest.mark.parametrize("field", ["price", "volume", "bid", "ask"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_ticks_are_rejected_before_any_effect(
    field: str, value: float
) -> None:
    with pytest.raises(ValueError, match="finite"):
        Tick(**{"symbol": "AAPL", "price": 1.0, field: value})
    tick = Tick(symbol="AAPL", price=1.0)
    setattr(tick, field, value)
    bus = MarketFeedBus()
    seen: list[object] = []
    bus.subscribe_ticks("AAPL", seen.append)
    bus.subscribe_bars("AAPL", 60, seen.append)
    with pytest.raises(ValueError, match="finite"):
        await bus.publish_tick(tick)
    assert seen == []
    assert bus.total_ticks == 0
    aggregator = TickAggregator("AAPL")
    with pytest.raises(ValueError, match="finite"):
        aggregator.on_tick(tick)
    assert aggregator.total_ticks == 0
    bar = LiveBar("AAPL")
    with pytest.raises(ValueError, match="finite"):
        bar.update(tick)
    assert bar.is_empty


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.10")
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_alert_threshold_is_rejected(value: float) -> None:
    bus = MarketFeedBus()
    with pytest.raises(ValueError, match="finite"):
        bus.add_price_alert("AAPL", value)
    assert bus.pending_alerts == 0
