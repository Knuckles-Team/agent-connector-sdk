"""Validate stock source pages delivered by an MCP connector."""

from __future__ import annotations

from enum import StrEnum

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
from scion_sdk.finance._stock_fields import _text
from scion_sdk.finance._stock_rules import _check_payload
from scion_sdk.finance.stock_image import _StockImageMixin
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.ports.session import McpSession


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
            self._check(record)
        except (ValueError, TypeError, OverflowError, KeyError):
            raise MalformedSourceDataError("invalid stock source record") from None
        return record

    def _check(self, record: SourceRecord) -> None:
        data = record.payload
        kind = self._stock_kind
        if (
            not isinstance(data, dict)
            or data.get("symbol") != self._symbol
            or data.get(_ID_FIELDS[kind]) != record.record_id
        ):
            raise ValueError("stock identity mismatch")
        _text(data, "license_tag")
        _check_payload(kind.value, data)

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
