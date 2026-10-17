"""Market feeds: live OHLCV bars from ticks, per-symbol fan-out and one-shot alerts."""

from __future__ import annotations

import pytest

from agent_connector_sdk.finance.feeds import (
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


async def test_bar_subscription_tracks_the_symbol() -> None:
    bus = MarketFeedBus()
    bus.subscribe_bars("AAPL", 60, lambda _bar: None)
    await bus.publish_tick(Tick(symbol="AAPL", price=1.0))
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
