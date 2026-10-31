"""Emerald-Exchange write-back sink (CONCEPT:AU-KG.ingest.enterprise-source-extractor) — HIGH-STAKES / propose-only.

Emits KG-derived trade intents as **proposed** orders. This sink is
``risk_tier="high_stakes"``: even with ``EMERALD_ENABLE_WRITE`` set it never
auto-executes — ``run_writeback`` routes its proposals to the approval queue, and
only an explicit ``approve`` (``_approved``) replays the order live via
``backend.submit_order``. The safety spine for finance writes.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core import WritebackContext, WritebackResult, register_sink

logger = logging.getLogger(__name__)


class EmeraldSink:
    domain = "emerald"
    enable_flag = "EMERALD_ENABLE_WRITE"
    risk_tier = "high_stakes"

    def _client(self, ops: dict[str, Any]) -> Any | None:
        client = ops.get("client")
        if client is not None:
            return client
        try:
            return _paper_backend(ops.get("backend_name", "paper"))
        except Exception:
            logger.debug("emerald backend unavailable", exc_info=True)
            return None

    def run(
        self, ctx: WritebackContext, ops: dict[str, Any], *, dry_run: bool
    ) -> WritebackResult:
        result = WritebackResult(target=self.domain)
        orders = ops.get("orders") or ops.get("creations") or []
        # Build proposals first (this is the dry-run / queued preview path).
        proposals = _order_proposals(orders, result)
        if dry_run:
            result.proposals.extend(proposals)
            return result

        # Live path: only reached on an approved replay (high_stakes never
        # auto-executes — run_writeback queues instead).
        client = self._client(ops)
        if client is None:
            result.skipped += len(proposals)
            return result
        for p in proposals:
            _submit_order(client, p, result)
        return result


def _paper_backend(name: str) -> Any:
    from emerald_exchange.backends import TradingMode, create_backend

    backend = create_backend(name=name, config={}, mode=TradingMode.PAPER)
    connect = getattr(backend, "connect", None)
    if callable(connect):
        connect()
    return backend


def _order_proposals(
    orders: list[dict[str, Any]], result: WritebackResult
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for o in orders:
        symbol = o.get("symbol")
        qty = o.get("qty") or o.get("quantity")
        if not symbol or not qty:
            result.skipped += 1
            continue
        proposals.append(
            {
                "op": "submit_order",
                "symbol": symbol,
                "side": (o.get("side") or "buy").lower(),
                "qty": qty,
                "order_type": (o.get("order_type") or "market").lower(),
                "limit_price": o.get("limit_price"),
            }
        )
    return proposals


def _order_enums() -> tuple[Any, Any]:
    try:
        from emerald_exchange.backends import OrderSide, OrderType
    except Exception:
        return None, None
    return OrderSide, OrderType


def _submit_order(client: Any, p: dict[str, Any], result: WritebackResult) -> None:
    order_side, order_type = _order_enums()
    try:
        side = order_side[p["side"].upper()] if order_side else p["side"]
        otype = order_type[p["order_type"].upper()] if order_type else p["order_type"]
        client.submit_order(
            p["symbol"],
            side,
            float(p["qty"]),
            order_type=otype,
            limit_price=p.get("limit_price"),
        )
        result.created += 1
    except Exception:
        logger.debug("emerald submit_order failed", exc_info=True)
        result.errors += 1


register_sink(EmeraldSink())
