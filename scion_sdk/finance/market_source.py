"""Bind and validate exchange, crypto and macro MCP source pages."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
)

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from scion_sdk.finance.stock_source import _date, _number, _text, _time
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.ports.session import McpSession


class MarketSourceKind(StrEnum):
    EXCHANGE_CANDLE = "exchange_candle"
    CMC_LISTING = "cmc_listing"
    CMC_GLOBAL = "cmc_global"
    FRED = "fred"
    FOMC = "fomc"
    ETF_FLOW = "etf"
    SENTIMENT = "sentiment"
    ONCHAIN_POSITION = "onchain"


_IDENTITIES = {
    MarketSourceKind.EXCHANGE_CANDLE: "candle_id",
    MarketSourceKind.CMC_LISTING: "cmc_id",
    MarketSourceKind.CMC_GLOBAL: "id",
    MarketSourceKind.FRED: "observation_id",
    MarketSourceKind.FOMC: "id",
    MarketSourceKind.ETF_FLOW: "record_id",
    MarketSourceKind.SENTIMENT: "record_id",
    MarketSourceKind.ONCHAIN_POSITION: "record_id",
}


def _candle(data: dict[str, Any]) -> None:
    for field in ("exchange", "symbol", "interval", "license_tag"):
        _text(data, field)
    _time(data.get("timestamp"))
    open_, high, low, close, _volume = (
        _number(data.get(field), nonnegative=True)
        for field in ("open", "high", "low", "close", "volume")
    )
    if high < max(open_, low, close) or low > min(open_, high, close):
        raise ValueError("invalid candle prices")


def _cmc(data: dict[str, Any], *, listing: bool) -> None:
    fields: tuple[str, ...]
    if listing:
        _text(data, "symbol")
        _text(data, "name")
        identifier = _text(data, "cmc_id")
        if (
            not identifier.isascii()
            or not identifier.isdecimal()
            or str(int(identifier)) != identifier
            or int(identifier) <= 0
        ):
            raise ValueError("invalid CMC identity")
        _number(data.get("price_usd"), nonnegative=True)
        fields = (
            "price_usd",
            "market_cap_usd",
            "volume_24h_usd",
            "circulating_supply",
            "total_supply",
            "max_supply",
        )
    else:
        if data.get("id") != "global":
            raise ValueError("invalid global market identity")
        _number(data.get("total_market_cap_usd"), nonnegative=True)
        fields = (
            "total_market_cap_usd",
            "total_volume_24h_usd",
            "btc_dominance",
            "eth_dominance",
            "active_cryptocurrencies",
        )
    for field in fields:
        if field in data:
            _number(data[field], nonnegative=True)
    _time(data.get("last_updated"))
    for field in ("percent_change_24h", "percent_change_7d"):
        if field in data:
            _number(data[field])


def _fred(data: dict[str, Any]) -> None:
    series = _text(data, "series_id")
    _date(data.get("date"))
    _date(data.get("realtime_start"))
    if data.get("realtime_end") is not None:
        _date(data["realtime_end"])
    if (
        data.get("observation_id")
        != f"{series}:{data['date']}:{data['realtime_start']}"
    ):
        raise ValueError("invalid observation identity")
    if "value" in data:
        _number(data["value"])


def _fomc(data: dict[str, Any]) -> None:
    _date(data.get("decision_date"))
    if data.get("id") != data["decision_date"]:
        raise ValueError("invalid announcement identity")
    _time(data.get("announcement_time_utc"))
    source = urlsplit(_text(data, "source_url"))
    if source.scheme != "https" or source.netloc != "www.federalreserve.gov":
        raise ValueError("invalid announcement provenance")
    if data.get("outcome") not in {"hike", "cut", "hold"}:
        raise ValueError("invalid announcement outcome")


def _panel(data: dict[str, Any], kind: MarketSourceKind) -> None:
    if data.get("dataset") != kind.value or data.get("provider") != "coinglass":
        raise ValueError("invalid macro source provenance")
    _text(data, "license_tag")
    _time(data.get("event_time"))
    _time(data.get("observed_at"))
    if kind is MarketSourceKind.ETF_FLOW:
        _text(data, "ticker")
        _number(data.get("net_flow_usd"))
    elif kind is MarketSourceKind.SENTIMENT:
        _number(data.get("value"))
    else:
        wallet = _text(data, "wallet")
        if not re.fullmatch(r"0x[0-9a-f]{40}", wallet):
            raise ValueError("invalid on-chain identity")
        _text(data, "symbol")
        _number(data.get("position_size"))
        _number(data.get("entry_price"), nonnegative=True)
        _number(data.get("mark_price"), nonnegative=True)


class MarketSourceAdapter:
    """Validate bound provider records before submission to any sink."""

    kind = "market_mcp"

    def __init__(
        self,
        source: McpToolSourceAdapter,
        *,
        market_kind: MarketSourceKind,
        connector: str,
        stream: str,
    ) -> None:
        if not isinstance(market_kind, MarketSourceKind) or not all(
            isinstance(value, str) and value.strip() for value in (connector, stream)
        ):
            raise ValueError("market source requires a kind, connector and stream")
        self._source, self._market_kind = source, market_kind
        self._connector, self._stream = connector, stream

    def describe(self) -> CapabilityDescriptor:
        return self._source.describe().model_copy(update={"kind": self.kind})

    async def discover(self, session: McpSession) -> StreamDescriptor:
        descriptor = await self._source.discover(session)
        if descriptor.stream != self._stream:
            raise SourceContractError("market source stream does not match")
        return descriptor

    def _validated(self, record: SourceRecord) -> SourceRecord:
        try:
            data = record.payload
            if (
                not isinstance(data, dict)
                or record.provenance.connector != self._connector
                or record.stream != self._stream
                or data.get(_IDENTITIES[self._market_kind]) != record.record_id
            ):
                raise ValueError("market source identity mismatch")
            if self._market_kind is MarketSourceKind.EXCHANGE_CANDLE:
                _candle(data)
            elif self._market_kind is MarketSourceKind.CMC_LISTING:
                _cmc(data, listing=True)
            elif self._market_kind is MarketSourceKind.CMC_GLOBAL:
                _cmc(data, listing=False)
            elif self._market_kind is MarketSourceKind.FRED:
                _fred(data)
            elif self._market_kind is MarketSourceKind.FOMC:
                _fomc(data)
            else:
                _panel(data, self._market_kind)
            return record
        except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
            raise MalformedSourceDataError("invalid market source record") from None

    async def extract(
        self, session: McpSession, checkpoint: SourceCheckpoint | None
    ) -> RecordPage:
        page = await self._source.extract(session, checkpoint)
        if (
            page.mode is not SourceIngestionMode.DELTA
            or page.withdrawals
            or page.authoritative_live_ids is not None
        ):
            raise SourceContractError(
                "market sources require non-authoritative delta pages"
            )
        records = tuple(self._validated(record) for record in page.records)
        if len({record.record_id for record in records}) != len(records):
            raise MalformedSourceDataError("duplicate market source identity")
        return page.model_copy(update={"records": records})

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        raise SourceContractError(
            "market sources do not provide complete reconciliation"
        )
