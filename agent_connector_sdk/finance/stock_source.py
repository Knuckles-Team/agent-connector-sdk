"""Validate stock source pages delivered by an MCP connector."""

from __future__ import annotations

import base64
import hashlib
import math
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
    SourceRecord,
)

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.contracts import (
    CapabilityDescriptor,
    ReconciliationReport,
    RecordPage,
    StreamDescriptor,
)
from agent_connector_sdk.finance.stock_image import _StockImageMixin
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.ports.session import McpSession


class StockSourceKind(StrEnum):
    BAR = "bar"
    QUOTE = "quote"
    NEWS = "news"
    DIVIDEND = "dividend"
    PROFILE = "profile"
    INCOME = "income"
    EARNINGS = "earnings"
    LOGO = "logo"


_ID_FIELDS = {
    StockSourceKind.BAR: "bar_id",
    StockSourceKind.QUOTE: "quote_id",
    StockSourceKind.NEWS: "news_id",
    StockSourceKind.DIVIDEND: "dividend_id",
    StockSourceKind.PROFILE: "record_id",
    StockSourceKind.INCOME: "record_id",
    StockSourceKind.EARNINGS: "record_id",
    StockSourceKind.LOGO: "record_id",
}


def _number(value: Any, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid stock value")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("invalid stock value")
    return result


def _date(value: Any) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid stock date")


def _time(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("invalid stock timestamp")
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("stock timestamp must have an offset")


def _text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stock field is required")
    return value


class StockSourceAdapter(_StockImageMixin):
    """Check source identities and domain fields before a stock page is committed."""

    kind = "stock_mcp"

    def __init__(
        self, source: McpToolSourceAdapter, *, stock_kind: StockSourceKind, symbol: str
    ) -> None:
        if (
            not isinstance(stock_kind, StockSourceKind)
            or not isinstance(symbol, str)
            or not symbol.strip()
        ):
            raise ValueError("stock source requires a kind and symbol")
        self._source, self._stock_kind, self._symbol = source, stock_kind, symbol

    def describe(self) -> CapabilityDescriptor:
        return self._source.describe().model_copy(update={"kind": self.kind})

    async def discover(self, session: McpSession) -> StreamDescriptor:
        return await self._source.discover(session)

    def _validated(self, record: SourceRecord) -> SourceRecord:
        try:
            data = record.payload
            kind = self._stock_kind
            if (
                not isinstance(data, dict)
                or data.get("symbol") != self._symbol
                or data.get(_ID_FIELDS[kind]) != record.record_id
            ):
                raise ValueError("stock identity mismatch")
            _text(data, "license_tag")
            if kind in (StockSourceKind.BAR, StockSourceKind.QUOTE):
                _time(data.get("timestamp"))
                _text(data, "feed")
                scope = _text(data, "session_scope")
                if scope not in {"feed_native", "alpaca_calendar"}:
                    raise ValueError("invalid stock session scope")
                if kind is StockSourceKind.BAR:
                    _text(data, "timeframe")
                    if data.get("adjustment") not in {
                        "raw",
                        "split",
                        "dividend",
                        "spin-off",
                        "all",
                    }:
                        raise ValueError("invalid stock adjustment")
                    o, h, low, close, _volume = (
                        _number(data.get(k), nonnegative=True)
                        for k in ("open", "high", "low", "close", "volume")
                    )
                    if h < max(o, low, close) or low > min(o, h, close):
                        raise ValueError("invalid stock prices")
                    if scope == "alpaca_calendar" and data.get("session") not in {
                        "pre_market",
                        "regular",
                        "post_market",
                        "outside_session",
                    }:
                        raise ValueError("invalid stock session")
                else:
                    for field in ("bid", "ask", "bid_size", "ask_size"):
                        _number(data.get(field), nonnegative=True)
            elif kind is StockSourceKind.NEWS:
                for field in ("headline", "author", "source"):
                    _text(data, field)
                _time(data.get("created_at"))
                _time(data.get("updated_at"))
            elif kind is StockSourceKind.DIVIDEND:
                if data.get("kind") not in {"cash", "stock"}:
                    raise ValueError("invalid dividend type")
                _number(data.get("rate"), nonnegative=True)
                _date(data.get("process_date"))
                _date(data.get("ex_date"))
                for field in ("record_date", "payable_date"):
                    if field in data:
                        _date(data[field])
            else:
                if data.get("dataset") != kind.value:
                    raise ValueError("company dataset mismatch")
                _text(data, "provider")
                _time(data.get("observed_at"))
                if kind is StockSourceKind.PROFILE:
                    _text(data, "company_name")
                elif kind is StockSourceKind.INCOME:
                    _date(data.get("period_date"))
                    if data.get("period") not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
                        raise ValueError("invalid company period")
                    _text(data, "currency")
                    _number(data.get("revenue"))
                    _number(data.get("net_income"))
                elif kind is StockSourceKind.EARNINGS:
                    _date(data.get("announcement_date"))
                    for field in (
                        "eps_actual",
                        "eps_estimated",
                        "revenue_actual",
                        "revenue_estimated",
                    ):
                        if field in data:
                            _number(data[field])
                else:
                    if data.get("image_media_type") != "image/png":
                        raise ValueError("invalid logo format")
                    encoded = _text(data, "image_base64")
                    if len(encoded) > 1_398_104:
                        raise ValueError("invalid logo size")
                    image = base64.b64decode(encoded, validate=True)
                    if (
                        len(image) > 1024 * 1024
                        or not image.startswith(b"\x89PNG\r\n\x1a\n")
                        or hashlib.sha256(image).hexdigest() != data.get("image_sha256")
                    ):
                        raise ValueError("invalid logo digest")
            return record
        except (ValueError, TypeError, OverflowError, KeyError):
            raise MalformedSourceDataError("invalid stock source record") from None

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
                "stock sources require non-authoritative delta pages"
            )
        records = tuple(self._validated(record) for record in page.records)
        if len({record.record_id for record in records}) != len(records):
            raise MalformedSourceDataError("duplicate stock source identity")
        return page.model_copy(update={"records": records})

    async def reconcile(
        self, session: McpSession, known_ids: frozenset[str]
    ) -> ReconciliationReport:
        """A bounded window cannot prove that absent records were deleted."""
        raise SourceContractError(
            "stock sources do not provide complete reconciliation"
        )
