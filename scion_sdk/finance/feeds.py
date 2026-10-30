"""Real-time market feeds on :class:`~scion_sdk.streaming.StreamBus`.

Ticks are published by symbol and aggregated into live OHLCV bars.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

from scion_sdk.finance._feed_aggregator import TickAggregator
from scion_sdk.finance._feed_types import (
    LiveBar,
    Tick,
    _crossed,
    _require_bar_size,
    _validate_tick,
)
from scion_sdk.streaming import CallbackSubscriber, StreamBus, StreamMessage

logger = logging.getLogger(__name__)


__all__ = ["LiveBar", "MarketFeedBus", "Tick", "TickAggregator"]


class MarketFeedBus:
    """
    Finance-specific adapter on top of the universal StreamBus.

    Handles:
    - Symbol-specific topic routing (market.{symbol}.ticks)
    - Tick-to-bar aggregation
    - Multi-symbol subscription management
    - Price alert triggers

    Usage:
        bus = MarketFeedBus()
        bus.subscribe_ticks("AAPL", my_callback)
        await bus.publish_tick(Tick(symbol="AAPL", price=150.0))
    """

    def __init__(self, bus: StreamBus | None = None):
        self.bus = bus or StreamBus()
        self._aggregators: dict[str, dict[int, TickAggregator]] = {}
        self._alerts: list[dict[str, Any]] = []
        self._tick_count = 0

    def subscribe_ticks(self, symbol: str, callback: Callable[[Any], Any]) -> None:
        """Subscribe to real-time ticks for a symbol."""
        topic = f"market.{symbol}.ticks"
        sub = CallbackSubscriber(on_message_fn=callback)
        self.bus.subscribe(topic, sub)

    def subscribe_bars(
        self, symbol: str, bar_size: int, callback: Callable[[Any], Any]
    ) -> None:
        """Subscribe to aggregated bars for a symbol."""
        _require_bar_size(bar_size)
        topic = f"market.{symbol}.bars.{bar_size}s"
        sub = CallbackSubscriber(on_message_fn=callback)
        self.bus.subscribe(topic, sub)

        aggregators = self._aggregators.setdefault(symbol, {})
        if bar_size not in aggregators:
            aggregators[bar_size] = TickAggregator(symbol, bar_size)

    def add_price_alert(
        self,
        symbol: str,
        price: float,
        direction: str = "above",
        callback: Callable[[Any], Any] | None = None,
    ) -> None:
        """Set a price alert that triggers when price crosses a level."""
        if not math.isfinite(price):
            raise ValueError("market alert threshold must be finite")
        self._alerts.append(
            {
                "symbol": symbol,
                "price": price,
                "direction": direction,
                "callback": callback,
                "triggered": False,
            }
        )

    async def publish_tick(self, tick: Tick) -> int:
        """
        Publish a tick to the bus and process aggregations/alerts.
        """
        _validate_tick(tick)
        self._tick_count += 1

        msg = StreamMessage(
            topic=f"market.{tick.symbol}.ticks",
            data={
                "price": tick.price,
                "volume": tick.volume,
                "bid": tick.bid,
                "ask": tick.ask,
            },
            source="market_feed",
        )
        delivered = await self.bus.publish(msg)

        delivered += await self._publish_bars(tick)
        self._fire_alerts(tick)
        return delivered

    async def _publish_bars(self, tick: Tick) -> int:
        delivered = 0
        for agg in self._aggregators.get(tick.symbol, {}).values():
            completed = agg.on_tick(tick)
            if completed:
                bar_msg = StreamMessage(
                    topic=f"market.{tick.symbol}.bars.{agg.bar_size}s",
                    data=completed.to_dict(),
                    source="market_feed_aggregator",
                )
                delivered += await self.bus.publish(bar_msg)
        return delivered

    def _fire_alerts(self, tick: Tick) -> None:
        for alert in self._alerts:
            if alert["triggered"] or alert["symbol"] != tick.symbol:
                continue
            if _crossed(alert, tick):
                alert["triggered"] = True
                if alert["callback"]:
                    alert["callback"](tick)

    @property
    def total_ticks(self) -> int:
        return self._tick_count

    @property
    def active_symbols(self) -> list[str]:
        return list(self._aggregators.keys())

    @property
    def pending_alerts(self) -> int:
        return sum(1 for a in self._alerts if not a["triggered"])
