"""Bind and validate exchange, crypto and macro MCP source pages."""

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
from scion_sdk.finance._market_rules import _check_market
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
            self._check(record)
        except (ValueError, TypeError, OverflowError, KeyError, AttributeError):
            raise MalformedSourceDataError("invalid market source record") from None
        return record

    def _check(self, record: SourceRecord) -> None:
        data = record.payload
        if (
            not isinstance(data, dict)
            or record.provenance.connector != self._connector
            or record.stream != self._stream
            or data.get(_IDENTITIES[self._market_kind]) != record.record_id
        ):
            raise ValueError("market source identity mismatch")
        _check_market(self._market_kind, data)

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
